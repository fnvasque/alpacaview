import json
import sys
from typing import Optional

import click
import requests

from src.signal_generator.config import SignalGeneratorSettings
from src.signal_generator.data_fetcher import DataFetchError, fetch_ohlcv
from src.signal_generator.indicators import compute_indicators
from src.signal_generator.signal_builder import build_payload


@click.command()
@click.option("--force", is_flag=True, default=False, help="Generate signal without crossover (test mode).")
@click.option("--send", is_flag=True, default=False, help="POST to backend.")
@click.option("--dry-run", "dry_run", is_flag=True, default=False, help="Print payload to stdout (default behavior).")
@click.option("--ticker", default=None, help="Override tickers list with a single ticker.")
@click.option("--timeframe", default=None, help="Bar interval (e.g. 15m). Overrides SIGNAL_GENERATOR_TIMEFRAME.")
@click.option("--period", default=None, help="Lookback window (e.g. 5d). Overrides SIGNAL_GENERATOR_PERIOD.")
def main(
    force: bool,
    send: bool,
    dry_run: bool,
    ticker: Optional[str],
    timeframe: Optional[str],
    period: Optional[str],
) -> None:
    """
    Signal generator. Prints payload by default (dry-run).
    Use --send to POST to the backend webhook.
    Use --force to bypass the crossover check.
    """
    settings = SignalGeneratorSettings()

    if not settings.PYTHON_SIGNAL_GENERATOR_ENABLED:
        click.echo("PYTHON_SIGNAL_GENERATOR_ENABLED=false. Set to true to enable.")
        sys.exit(0)

    resolved_timeframe = timeframe or settings.SIGNAL_GENERATOR_TIMEFRAME
    resolved_period = period or settings.SIGNAL_GENERATOR_PERIOD
    tickers = [ticker.upper()] if ticker else settings.SIGNAL_GENERATOR_TICKERS

    for t in tickers:
        _run_for_ticker(
            t,
            settings,
            timeframe=resolved_timeframe,
            period=resolved_period,
            force=force,
            send=send,
        )


def _run_for_ticker(
    ticker: str,
    settings: SignalGeneratorSettings,
    timeframe: str,
    period: str,
    force: bool,
    send: bool,
) -> None:
    try:
        df = fetch_ohlcv(ticker, period, timeframe)
    except DataFetchError as exc:
        click.echo(f"[{ticker}] fetch failed: {exc}", err=True)
        sys.exit(1)

    result = compute_indicators(
        df,
        ticker,
        timeframe,
        settings.EMA_LENGTH,
        settings.ATR_LENGTH,
    )

    if result is None:
        click.echo(f"[{ticker}] no_signal: insufficient data for indicators")
        return

    if not force and not result.crossover_detected:
        click.echo(f"[{ticker}] no crossover detected")
        return

    payload = build_payload(
        result,
        settings.SIGNAL_GENERATOR_SECRET,
        settings.ATR_MULTIPLIER,
        settings.RISK_REWARD,
    )

    if payload is None:
        click.echo(f"[{ticker}] stop_loss <= 0, signal skipped")
        return

    if send:
        _post_payload(ticker, payload, settings.SIGNAL_GENERATOR_BACKEND_URL)
    else:
        click.echo(json.dumps(payload, indent=2))


def _post_payload(ticker: str, payload: dict, backend_url: str) -> None:
    url = f"{backend_url.rstrip('/')}/webhook/signal"
    try:
        resp = requests.post(url, json=payload, timeout=10)
    except requests.RequestException as exc:
        click.echo(f"[{ticker}] request failed: {exc}", err=True)
        sys.exit(1)

    try:
        body = resp.json()
    except Exception:
        body = {}

    if resp.status_code == 409 and body.get("reason_code") == "duplicate_signal":
        click.echo(f"[{ticker}] signal already processed")
        return

    if resp.status_code not in (200, 202):
        click.echo(
            f"[{ticker}] rejected ({resp.status_code}): reason_code={body.get('reason_code')} detail={body.get('reason_detail')}",
            err=True,
        )
        sys.exit(1)

    click.echo(
        f"[{ticker}] signal accepted: approved={body.get('approved')} signal_id={body.get('signal_id')}"
    )


if __name__ == "__main__":
    main()
