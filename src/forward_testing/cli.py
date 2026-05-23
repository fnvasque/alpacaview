import sys
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import click
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — registers all ORM models in Base.metadata
from app.database import Base
from app.models.forward_test_run import ForwardTestRun
from src.forward_testing.config import ForwardTestingSettings
from src.forward_testing.market_hours import is_market_open
from src.forward_testing.runner import RunResult, RunStatus, run_ticker


@click.command()
@click.option("--once", is_flag=True, default=False, help="No-op documentation flag for cron/launchd usage.")
@click.option("--tickers", default=None, help="Comma-separated tickers. Overrides FORWARD_TESTING_TICKERS.")
@click.option("--timeframe", default=None, help="Bar interval (e.g. 15m). Overrides FORWARD_TESTING_TIMEFRAME.")
@click.option("--period", default=None, help="Lookback window (e.g. 5d). Overrides FORWARD_TESTING_PERIOD.")
@click.option("--send", is_flag=True, default=False, help="POST to backend when signal found.")
@click.option("--dry-run", "dry_run", is_flag=True, default=False, help="Evaluate signals without sending. Writes to DB.")
@click.option("--market-hours-only", "market_hours_only", is_flag=True, default=False, help="Skip if outside US equity market hours.")
def main(
    once: bool,
    tickers: Optional[str],
    timeframe: Optional[str],
    period: Optional[str],
    send: bool,
    dry_run: bool,
    market_hours_only: bool,
) -> None:
    """Forward testing runner. Evaluates signal generator pipeline for all tickers and persists results."""
    settings = ForwardTestingSettings()

    if not settings.FORWARD_TESTING_ENABLED:
        click.echo("FORWARD_TESTING_ENABLED=false. Set to true to enable.")
        sys.exit(0)

    engine, Session = _init_db(settings.FORWARD_TESTING_DB_URL)
    db_session = Session()

    run_id = str(uuid4())
    now = datetime.now(timezone.utc)
    effective_dry_run = dry_run or not send

    resolved_tickers = _parse_tickers(tickers) or settings.FORWARD_TESTING_TICKERS
    resolved_timeframe = timeframe or settings.FORWARD_TESTING_TIMEFRAME
    resolved_period = period or settings.FORWARD_TESTING_PERIOD

    if market_hours_only and not is_market_open(now):
        for t in resolved_tickers:
            row = ForwardTestRun(
                run_id=run_id,
                ticker=t,
                timeframe=resolved_timeframe,
                period=resolved_period,
                status=RunStatus.SKIPPED_MARKET_CLOSED.value,
                is_dry_run=effective_dry_run,
            )
            db_session.add(row)
        try:
            db_session.commit()
        except Exception as exc:
            db_session.rollback()
            click.echo(f"DB write failed: {exc}", err=True)
        click.echo(f"Market closed. Skipped {len(resolved_tickers)} tickers.")
        db_session.close()
        sys.exit(0)

    has_error = False
    for t in resolved_tickers:
        result = run_ticker(
            t, resolved_timeframe, resolved_period, settings,
            send=send, dry_run=effective_dry_run,
        )
        try:
            _persist(run_id, result, effective_dry_run, db_session)
        except Exception as exc:
            click.echo(f"[{t}] DB write failed: {exc}", err=True)
            has_error = True
        _echo_result(t, result)
        if result.status in (RunStatus.ERROR, RunStatus.SIGNAL_SENT):
            has_error = True

    db_session.close()
    sys.exit(1 if has_error else 0)


def _init_db(db_url: str) -> tuple:
    connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
    engine = create_engine(db_url, connect_args=connect_args)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def _persist(run_id: str, result: RunResult, is_dry_run: bool, session) -> None:
    row = ForwardTestRun(
        run_id=run_id,
        ticker=result.ticker,
        timeframe=result.timeframe,
        period=result.period,
        status=result.status.value,
        is_dry_run=is_dry_run,
        bar_time=result.bar_time,
        client_signal_id=result.client_signal_id,
        price=result.price,
        stop_loss=result.stop_loss,
        take_profit=result.take_profit,
        risk_reward=result.risk_reward,
        backend_status_code=result.backend_status_code,
        backend_signal_id=result.backend_signal_id,
        backend_approved=result.backend_approved,
        backend_reason_code=result.backend_reason_code,
        backend_reason_detail=result.backend_reason_detail,
        error_message=result.error_message,
    )
    session.add(row)
    session.commit()


def _echo_result(ticker: str, result: RunResult) -> None:
    if result.status == RunStatus.SIGNAL_CANDIDATE:
        click.echo(
            f"[{ticker}] signal_candidate: price={result.price} sl={result.stop_loss} "
            f"tp={result.take_profit} rr={result.risk_reward} id={result.client_signal_id}"
        )
    elif result.status == RunStatus.RISK_APPROVED:
        click.echo(
            f"[{ticker}] risk_approved: signal_id={result.backend_signal_id} "
            f"reason_code={result.backend_reason_code}"
        )
    elif result.status == RunStatus.RISK_REJECTED:
        click.echo(
            f"[{ticker}] risk_rejected: reason_code={result.backend_reason_code} "
            f"detail={result.backend_reason_detail}"
        )
    elif result.status == RunStatus.DUPLICATE_SIGNAL:
        click.echo(f"[{ticker}] duplicate_signal: already processed")
    elif result.status == RunStatus.NO_SIGNAL:
        click.echo(f"[{ticker}] no_signal")
    elif result.status == RunStatus.INSUFFICIENT_DATA:
        click.echo(f"[{ticker}] insufficient_data")
    elif result.status == RunStatus.SKIPPED_MARKET_CLOSED:
        click.echo(f"[{ticker}] skipped_market_closed")
    elif result.status == RunStatus.SIGNAL_SENT:
        click.echo(
            f"[{ticker}] signal_sent: unexpected HTTP {result.backend_status_code}",
            err=True,
        )
    elif result.status == RunStatus.ERROR:
        click.echo(f"[{ticker}] error: {result.error_message}", err=True)


def _parse_tickers(tickers_str: Optional[str]) -> Optional[list[str]]:
    if tickers_str is None:
        return None
    return [t.strip().upper() for t in tickers_str.split(",") if t.strip()]


if __name__ == "__main__":
    main()
