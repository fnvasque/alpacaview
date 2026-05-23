from enum import Enum


class SignalSide(str, Enum):
    """Trade direction. Both values are schema-valid; SELL is rejected at service layer."""
    BUY = "buy"
    SELL = "sell"


class SignalStatus(str, Enum):
    """Lifecycle status of a Signal that reached the Risk Engine."""
    RECEIVED = "received"
    RISK_APPROVED = "risk_approved"
    RISK_REJECTED = "risk_rejected"


class WebhookEventType(str, Enum):
    """Event types for pre-engine rejections stored in webhook_events audit table."""
    AUTH_FAILED = "auth_failed"
    SCHEMA_INVALID = "schema_invalid"
    UNSUPPORTED_SIDE = "unsupported_side"
    UNSUPPORTED_ASSET_CLASS = "unsupported_asset_class"
    SIGNAL_QUALITY_REJECTED = "signal_quality_rejected"
    DUPLICATE_SIGNAL = "duplicate_signal"
    INTERNAL_ERROR = "internal_error"


class RejectionReason(str, Enum):
    """
    Machine-readable rejection reasons.

    Enforced in V0: INVALID_SECRET, SCHEMA_INVALID, UNSUPPORTED_SIDE,
    UNSUPPORTED_ASSET_CLASS, DUPLICATE_SIGNAL, KILL_SWITCH_ACTIVE,
    MAX_DAILY_TRADES_REACHED.

    Deferred to V1/V2 (logged, not enforced in V0): DAILY_TARGET_REACHED,
    DAILY_LOSS_LIMIT_EXCEEDED, WEEKLY_LOSS_LIMIT_EXCEEDED,
    CONSECUTIVE_LOSSES_EXCEEDED.
    """
    # Enforced
    INVALID_SECRET = "invalid_secret"
    SCHEMA_INVALID = "schema_invalid"
    UNSUPPORTED_SIDE = "unsupported_side"
    UNSUPPORTED_ASSET_CLASS = "unsupported_asset_class"
    DUPLICATE_SIGNAL = "duplicate_signal"
    KILL_SWITCH_ACTIVE = "kill_switch_active"
    MAX_DAILY_TRADES_REACHED = "max_daily_trades_reached"
    # Signal quality (V0.1)
    INVALID_PRICE = "invalid_price"
    INVALID_STOP_LOSS = "invalid_stop_loss"
    INVALID_TAKE_PROFIT = "invalid_take_profit"
    STOP_LOSS_ABOVE_ENTRY = "stop_loss_above_entry"
    TAKE_PROFIT_BELOW_ENTRY = "take_profit_below_entry"
    RISK_REWARD_TOO_LOW = "risk_reward_too_low"
    UNSUPPORTED_TIMEFRAME = "unsupported_timeframe"
    STALE_SIGNAL = "stale_signal"
    # Deferred (V1/V2)
    DAILY_TARGET_REACHED = "daily_target_reached"
    DAILY_LOSS_LIMIT_EXCEEDED = "daily_loss_limit_exceeded"
    WEEKLY_LOSS_LIMIT_EXCEEDED = "weekly_loss_limit_exceeded"
    CONSECUTIVE_LOSSES_EXCEEDED = "consecutive_losses_exceeded"
    # Infrastructure failures
    INTERNAL_ERROR = "internal_error"
