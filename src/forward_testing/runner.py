from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

import requests

from src.forward_testing.config import ForwardTestingSettings
from src.signal_generator.data_fetcher import DataFetchError, fetch_ohlcv
from src.signal_generator.indicators import compute_indicators
from src.signal_generator.signal_builder import build_payload


class RunStatus(str, Enum):
    NO_SIGNAL = "no_signal"
    SIGNAL_CANDIDATE = "signal_candidate"
    SIGNAL_SENT = "signal_sent"
    RISK_APPROVED = "risk_approved"
    RISK_REJECTED = "risk_rejected"
    DUPLICATE_SIGNAL = "duplicate_signal"
    SKIPPED_MARKET_CLOSED = "skipped_market_closed"
    INSUFFICIENT_DATA = "insufficient_data"
    ERROR = "error"


@dataclass
class RunResult:
    ticker: str
    timeframe: str
    period: str
    status: RunStatus
    bar_time: Optional[datetime] = None
    client_signal_id: Optional[str] = None
    price: Optional[str] = None
    stop_loss: Optional[str] = None
    take_profit: Optional[str] = None
    risk_reward: Optional[str] = None
    backend_status_code: Optional[int] = None
    backend_signal_id: Optional[str] = None
    backend_approved: Optional[bool] = None
    backend_reason_code: Optional[str] = None
    backend_reason_detail: Optional[str] = None
    error_message: Optional[str] = None


def run_ticker(
    ticker: str,
    timeframe: str,
    period: str,
    settings: ForwardTestingSettings,
    send: bool,
    dry_run: bool,
) -> RunResult:
    # Step 1 — Fetch OHLCV
    try:
        df = fetch_ohlcv(ticker, period, timeframe)
    except DataFetchError as exc:
        return RunResult(ticker, timeframe, period, RunStatus.ERROR, error_message=str(exc))
    except Exception as exc:
        return RunResult(ticker, timeframe, period, RunStatus.ERROR, error_message=f"unexpected: {exc}")

    # Step 2 — Compute indicators
    result = compute_indicators(df, ticker, timeframe, settings.EMA_LENGTH, settings.ATR_LENGTH)
    if result is None:
        return RunResult(
            ticker, timeframe, period,
            RunStatus.INSUFFICIENT_DATA,
            error_message="insufficient data for indicators",
        )

    # Step 3 — Crossover check
    if not result.crossover_detected:
        return RunResult(ticker, timeframe, period, RunStatus.NO_SIGNAL, bar_time=result.bar_time)

    # Step 4 — Build payload
    payload = build_payload(result, settings.FORWARD_TESTING_SECRET, settings.ATR_MULTIPLIER, settings.RISK_REWARD)
    if payload is None:
        return RunResult(
            ticker, timeframe, period,
            RunStatus.NO_SIGNAL,
            bar_time=result.bar_time,
            error_message="stop_loss <= 0",
        )

    # Step 5 — Compute risk_reward
    price_d = Decimal(payload["price"])
    sl_d = Decimal(payload["stop_loss"])
    tp_d = Decimal(payload["take_profit"])
    rr = (tp_d - price_d) / (price_d - sl_d)
    rr_str = f"{rr:.4f}"

    # Step 6 — Build shared signal fields
    signal_fields: dict = dict(
        bar_time=result.bar_time,
        client_signal_id=payload["client_signal_id"],
        price=payload["price"],
        stop_loss=payload["stop_loss"],
        take_profit=payload["take_profit"],
        risk_reward=rr_str,
    )

    # Step 7 — Dry-run dispatch
    if dry_run:
        return RunResult(ticker, timeframe, period, RunStatus.SIGNAL_CANDIDATE, **signal_fields)

    # Step 8 — Send mode
    if send:
        url = f"{settings.FORWARD_TESTING_BACKEND_URL.rstrip('/')}/webhook/signal"
        try:
            resp = requests.post(url, json=payload, timeout=10)
        except requests.RequestException as exc:
            return RunResult(ticker, timeframe, period, RunStatus.ERROR, **signal_fields, error_message=str(exc))

        try:
            body = resp.json()
        except Exception:
            body = {}

        if resp.status_code == 409 and body.get("reason_code") == "duplicate_signal":
            return RunResult(
                ticker, timeframe, period,
                RunStatus.DUPLICATE_SIGNAL,
                **signal_fields,
                backend_status_code=409,
                backend_reason_code="duplicate_signal",
            )

        if resp.status_code == 202:
            return RunResult(
                ticker, timeframe, period,
                RunStatus.RISK_APPROVED,
                **signal_fields,
                backend_status_code=202,
                backend_signal_id=body.get("signal_id"),
                backend_approved=True,
                backend_reason_code=body.get("reason_code"),
                backend_reason_detail=body.get("reason_detail"),
            )

        if resp.status_code == 200:
            return RunResult(
                ticker, timeframe, period,
                RunStatus.RISK_REJECTED,
                **signal_fields,
                backend_status_code=200,
                backend_signal_id=body.get("signal_id"),
                backend_approved=False,
                backend_reason_code=body.get("reason_code"),
                backend_reason_detail=body.get("reason_detail"),
            )

        return RunResult(
            ticker, timeframe, period,
            RunStatus.SIGNAL_SENT,
            **signal_fields,
            backend_status_code=resp.status_code,
            backend_reason_code=body.get("reason_code"),
            backend_reason_detail=body.get("reason_detail"),
            error_message=f"unexpected HTTP {resp.status_code}",
        )

    # Step 9 — Fallback: neither --send nor --dry-run (CLI effective_dry_run guards this)
    return RunResult(ticker, timeframe, period, RunStatus.SIGNAL_CANDIDATE, **signal_fields)
