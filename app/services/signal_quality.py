from datetime import datetime
from typing import Optional

from app.config import Settings
from app.schemas.enums import RejectionReason
from app.schemas.signal import WebhookSignalRequest


def validate_signal_quality(
    signal: WebhookSignalRequest,
    settings: Settings,
    now: datetime,
) -> Optional[tuple[RejectionReason, Optional[str]]]:
    """
    Pure quality gate for BUY signals.

    Returns (RejectionReason, detail_str) on first failure, None if all checks pass.
    No DB access, no I/O, no side effects. `now` is injected for deterministic testing.
    """
    if signal.price <= 0:
        return (RejectionReason.INVALID_PRICE, f"price={signal.price}")

    if signal.stop_loss is None or signal.stop_loss <= 0:
        return (RejectionReason.INVALID_STOP_LOSS, f"stop_loss={signal.stop_loss}")

    if signal.take_profit is None or signal.take_profit <= 0:
        return (RejectionReason.INVALID_TAKE_PROFIT, f"take_profit={signal.take_profit}")

    # Covers equality: sl == price → division by zero in rr calc
    if signal.stop_loss >= signal.price:
        return (
            RejectionReason.STOP_LOSS_ABOVE_ENTRY,
            f"stop_loss={signal.stop_loss} price={signal.price}",
        )

    # Covers equality: tp == price → zero reward
    if signal.take_profit <= signal.price:
        return (
            RejectionReason.TAKE_PROFIT_BELOW_ENTRY,
            f"take_profit={signal.take_profit} price={signal.price}",
        )

    risk = signal.price - signal.stop_loss  # > 0 guaranteed by prior checks
    reward = signal.take_profit - signal.price  # > 0 guaranteed by prior checks
    risk_reward = reward / risk
    if risk_reward < settings.MIN_RISK_REWARD:
        return (
            RejectionReason.RISK_REWARD_TOO_LOW,
            f"risk_reward={risk_reward:.4f} min={settings.MIN_RISK_REWARD}",
        )

    # Empty list = allow all timeframes
    if settings.ALLOWED_TIMEFRAMES and signal.timeframe not in settings.ALLOWED_TIMEFRAMES:
        return (
            RejectionReason.UNSUPPORTED_TIMEFRAME,
            f"timeframe={signal.timeframe} allowed={settings.ALLOWED_TIMEFRAMES}",
        )

    # MAX_SIGNAL_AGE_SECONDS=0 disables staleness check
    if settings.MAX_SIGNAL_AGE_SECONDS > 0:
        age_seconds = (now - signal.event_time).total_seconds()
        if age_seconds > settings.MAX_SIGNAL_AGE_SECONDS:
            return (
                RejectionReason.STALE_SIGNAL,
                f"age_seconds={age_seconds:.0f} max={settings.MAX_SIGNAL_AGE_SECONDS}",
            )

    return None
