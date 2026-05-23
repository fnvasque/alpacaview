from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from src.signal_generator.indicators import IndicatorResult

STRATEGY: str = "python_atr_generator"
VERSION: str = "0.2b.0"


def _bar_time_to_z(bar_time: datetime) -> str:
    """Format UTC datetime as ISO 8601 with Z suffix: 2026-05-20T14:30:00Z"""
    return bar_time.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_client_signal_id(ticker: str, timeframe: str, bar_time: datetime) -> str:
    return f"{STRATEGY}:{VERSION}:{ticker}:{timeframe}:{_bar_time_to_z(bar_time)}:buy"


def build_payload(
    result: IndicatorResult,
    secret: str,
    atr_multiplier: Decimal,
    risk_reward: Decimal,
) -> Optional[dict]:
    price = result.current_close
    stop_loss = price - result.current_atr * atr_multiplier

    if stop_loss <= 0:
        return None

    risk = price - stop_loss
    take_profit = price + risk * risk_reward

    bar_time_str = _bar_time_to_z(result.bar_time)
    event_time_str = _bar_time_to_z(datetime.now(timezone.utc))

    return {
        "secret": secret,
        "strategy": STRATEGY,
        "version": VERSION,
        "ticker": result.ticker,
        "side": "buy",
        "price": f"{price:.4f}",
        "stop_loss": f"{stop_loss:.4f}",
        "take_profit": f"{take_profit:.4f}",
        "timeframe": result.timeframe,
        "bar_time": bar_time_str,
        "event_time": event_time_str,
        "client_signal_id": build_client_signal_id(result.ticker, result.timeframe, result.bar_time),
    }
