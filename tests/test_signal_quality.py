"""
Pure unit tests for app.services.signal_quality.validate_signal_quality.

No DB, no TestClient — only function calls with crafted inputs.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from app.config import Settings
from app.schemas.enums import RejectionReason
from app.schemas.signal import WebhookSignalRequest
from app.services.signal_quality import validate_signal_quality


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_signal(**overrides) -> WebhookSignalRequest:
    base = {
        "secret": "s",
        "client_signal_id": str(uuid4()),
        "strategy": "momentum_pullback",
        "version": "1.0",
        "ticker": "SPY",
        "side": "buy",
        "price": Decimal("450.00"),
        "stop_loss": Decimal("445.00"),
        "take_profit": Decimal("458.00"),
        "timeframe": "5m",
        "bar_time": _now() - timedelta(minutes=5),
        "event_time": _now(),
    }
    base.update(overrides)
    return WebhookSignalRequest.model_validate(base)


def _make_settings(**overrides) -> Settings:
    base = dict(
        WEBHOOK_SECRET="s",
        DATABASE_URL="sqlite://",
        INITIAL_EQUITY=Decimal("10000"),
        STOP_AFTER_DAILY_TARGET=False,
        KILL_SWITCH=False,
        ALLOWED_TICKERS=["SPY"],
        MAX_DAILY_TRADES=3,
        MAX_DAILY_LOSS_PCT=Decimal("0.0075"),
        MAX_WEEKLY_LOSS_PCT=Decimal("0.025"),
        MAX_CONSECUTIVE_LOSSES=2,
        DAILY_TARGET_PCT=Decimal("0.003"),
        MIN_RISK_REWARD=Decimal("1.5"),
        ALLOWED_TIMEFRAMES=["5m", "15m", "1h"],
        MAX_SIGNAL_AGE_SECONDS=900,
        RESEND_RECEIVING_ENABLED=False,
        RESEND_API_KEY=None,
    )
    base.update(overrides)
    return Settings(**base)


# ── Happy path ─────────────────────────────────────────────────────────────────

def test_valid_signal_passes() -> None:
    assert validate_signal_quality(_make_signal(), _make_settings(), _now()) is None


def test_valid_signal_with_exact_min_rr_passes() -> None:
    # rr = (460 - 450) / (450 - 443.33...) = 1.5 exactly → passes
    signal = _make_signal(
        price=Decimal("450.00"),
        stop_loss=Decimal("440.00"),
        take_profit=Decimal("465.00"),  # rr = 15/10 = 1.5 exactly
    )
    assert validate_signal_quality(signal, _make_settings(), _now()) is None


# ── price ──────────────────────────────────────────────────────────────────────

def test_price_zero_returns_invalid_price() -> None:
    signal = _make_signal(price=Decimal("0"))
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.INVALID_PRICE


def test_price_negative_returns_invalid_price() -> None:
    signal = _make_signal(price=Decimal("-1"))
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.INVALID_PRICE


# ── stop_loss ──────────────────────────────────────────────────────────────────

def test_stop_loss_none_returns_invalid_stop_loss() -> None:
    signal = _make_signal(stop_loss=None)
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.INVALID_STOP_LOSS


def test_stop_loss_zero_returns_invalid_stop_loss() -> None:
    signal = _make_signal(stop_loss=Decimal("0"))
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.INVALID_STOP_LOSS


def test_stop_loss_negative_returns_invalid_stop_loss() -> None:
    signal = _make_signal(stop_loss=Decimal("-5"))
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.INVALID_STOP_LOSS


# ── take_profit ────────────────────────────────────────────────────────────────

def test_take_profit_none_returns_invalid_take_profit() -> None:
    signal = _make_signal(take_profit=None)
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.INVALID_TAKE_PROFIT


def test_take_profit_zero_returns_invalid_take_profit() -> None:
    signal = _make_signal(take_profit=Decimal("0"))
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.INVALID_TAKE_PROFIT


# ── stop_loss vs price ─────────────────────────────────────────────────────────

def test_stop_loss_equal_to_price_returns_stop_loss_above_entry() -> None:
    signal = _make_signal(
        price=Decimal("450"),
        stop_loss=Decimal("450"),
        take_profit=Decimal("460"),
    )
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.STOP_LOSS_ABOVE_ENTRY


def test_stop_loss_above_price_returns_stop_loss_above_entry() -> None:
    signal = _make_signal(
        price=Decimal("450"),
        stop_loss=Decimal("455"),
        take_profit=Decimal("460"),
    )
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.STOP_LOSS_ABOVE_ENTRY


# ── take_profit vs price ───────────────────────────────────────────────────────

def test_take_profit_equal_to_price_returns_take_profit_below_entry() -> None:
    signal = _make_signal(
        price=Decimal("450"),
        stop_loss=Decimal("445"),
        take_profit=Decimal("450"),
    )
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.TAKE_PROFIT_BELOW_ENTRY


def test_take_profit_below_price_returns_take_profit_below_entry() -> None:
    signal = _make_signal(
        price=Decimal("450"),
        stop_loss=Decimal("445"),
        take_profit=Decimal("440"),
    )
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.TAKE_PROFIT_BELOW_ENTRY


# ── risk/reward ────────────────────────────────────────────────────────────────

def test_rr_just_below_min_returns_risk_reward_too_low() -> None:
    # rr = 14/10 = 1.4 < 1.5
    signal = _make_signal(
        price=Decimal("450"),
        stop_loss=Decimal("440"),
        take_profit=Decimal("464"),  # reward=14, risk=10 → rr=1.4
    )
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.RISK_REWARD_TOO_LOW


def test_rr_custom_min_respected() -> None:
    # rr = 1.4 but MIN_RISK_REWARD=1.3 → passes
    signal = _make_signal(
        price=Decimal("450"),
        stop_loss=Decimal("440"),
        take_profit=Decimal("464"),
    )
    settings = _make_settings(MIN_RISK_REWARD=Decimal("1.3"))
    assert validate_signal_quality(signal, settings, _now()) is None


# ── timeframe ──────────────────────────────────────────────────────────────────

def test_unsupported_timeframe_returns_unsupported_timeframe() -> None:
    signal = _make_signal(timeframe="4h")
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.UNSUPPORTED_TIMEFRAME


def test_empty_allowed_timeframes_skips_check() -> None:
    signal = _make_signal(timeframe="4h")
    settings = _make_settings(ALLOWED_TIMEFRAMES=[])
    assert validate_signal_quality(signal, settings, _now()) is None


# ── staleness ──────────────────────────────────────────────────────────────────

def test_stale_signal_returns_stale_signal() -> None:
    now = _now()
    signal = _make_signal(event_time=now - timedelta(seconds=901))
    result = validate_signal_quality(signal, _make_settings(), now)
    assert result is not None
    assert result[0] == RejectionReason.STALE_SIGNAL


def test_signal_at_exact_age_limit_passes() -> None:
    now = _now()
    signal = _make_signal(event_time=now - timedelta(seconds=900))
    assert validate_signal_quality(signal, _make_settings(), now) is None


def test_max_signal_age_zero_disables_staleness_check() -> None:
    now = _now()
    signal = _make_signal(event_time=now - timedelta(days=365))
    settings = _make_settings(MAX_SIGNAL_AGE_SECONDS=0)
    assert validate_signal_quality(signal, settings, now) is None


# ── fail-fast order ────────────────────────────────────────────────────────────

def test_price_checked_before_stop_loss() -> None:
    # Both price and stop_loss are invalid — price must be caught first
    signal = _make_signal(price=Decimal("0"), stop_loss=None)
    result = validate_signal_quality(signal, _make_settings(), _now())
    assert result is not None
    assert result[0] == RejectionReason.INVALID_PRICE
