"""
Unit tests for src.signal_generator.signal_builder.

No I/O, no network. Uses a make_result() helper.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.signal_generator.indicators import IndicatorResult
from src.signal_generator.signal_builder import build_client_signal_id, build_payload

_UTC = timezone.utc
_BAR_TIME = datetime(2026, 5, 20, 14, 30, 0, tzinfo=_UTC)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_result(**overrides) -> IndicatorResult:
    base = dict(
        ticker="SPY",
        timeframe="15m",
        current_close=Decimal("450.0000"),
        current_ema=Decimal("448.0000"),
        current_atr=Decimal("2.0000"),
        previous_close=Decimal("447.0000"),
        previous_ema=Decimal("448.5000"),
        bar_time=_BAR_TIME,
        crossover_detected=True,
    )
    base.update(overrides)
    return IndicatorResult(**base)


# ── build_client_signal_id ─────────────────────────────────────────────────────

def test_client_signal_id_exact_format() -> None:
    cid = build_client_signal_id("SPY", "15m", _BAR_TIME)
    assert cid == "python_atr_generator:0.2b.0:SPY:15m:2026-05-20T14:30:00Z:buy"


def test_client_signal_id_uses_z_not_offset() -> None:
    cid = build_client_signal_id("SPY", "15m", _BAR_TIME)
    assert "Z" in cid
    assert "+00:00" not in cid


def test_client_signal_id_is_deterministic() -> None:
    id1 = build_client_signal_id("SPY", "15m", _BAR_TIME)
    id2 = build_client_signal_id("SPY", "15m", _BAR_TIME)
    assert id1 == id2


def test_client_signal_id_varies_by_ticker() -> None:
    id_spy = build_client_signal_id("SPY", "15m", _BAR_TIME)
    id_qqq = build_client_signal_id("QQQ", "15m", _BAR_TIME)
    assert id_spy != id_qqq


def test_client_signal_id_varies_by_bar_time() -> None:
    t1 = datetime(2026, 5, 20, 14, 30, 0, tzinfo=_UTC)
    t2 = datetime(2026, 5, 20, 14, 45, 0, tzinfo=_UTC)
    assert build_client_signal_id("SPY", "15m", t1) != build_client_signal_id("SPY", "15m", t2)


# ── build_payload ──────────────────────────────────────────────────────────────

def test_build_payload_stop_loss_calculation() -> None:
    # price=450, ATR=2, multiplier=1.5 → stop_loss = 450 - 3 = 447
    result = make_result(current_close=Decimal("450.0000"), current_atr=Decimal("2.0000"))
    payload = build_payload(result, "secret", Decimal("1.5"), Decimal("2.0"))
    assert payload is not None
    assert float(payload["stop_loss"]) == pytest.approx(447.0)


def test_build_payload_take_profit_calculation() -> None:
    # risk = 450-447 = 3, rr=2.0 → take_profit = 450 + 6 = 456
    result = make_result(current_close=Decimal("450.0000"), current_atr=Decimal("2.0000"))
    payload = build_payload(result, "secret", Decimal("1.5"), Decimal("2.0"))
    assert payload is not None
    assert float(payload["take_profit"]) == pytest.approx(456.0)


def test_build_payload_stop_loss_zero_returns_none() -> None:
    # price=1.0, ATR=1.0, multiplier=2.0 → stop_loss = 1 - 2 = -1
    result = make_result(current_close=Decimal("1.0000"), current_atr=Decimal("1.0000"))
    payload = build_payload(result, "secret", Decimal("2.0"), Decimal("2.0"))
    assert payload is None


def test_build_payload_bar_time_z_format() -> None:
    result = make_result(bar_time=_BAR_TIME)
    payload = build_payload(result, "secret", Decimal("1.5"), Decimal("2.0"))
    assert payload is not None
    assert payload["bar_time"] == "2026-05-20T14:30:00Z"


def test_build_payload_client_signal_id_matches_bar_time() -> None:
    result = make_result(bar_time=_BAR_TIME)
    payload = build_payload(result, "secret", Decimal("1.5"), Decimal("2.0"))
    assert payload is not None
    assert payload["client_signal_id"] == "python_atr_generator:0.2b.0:SPY:15m:2026-05-20T14:30:00Z:buy"


def test_build_payload_price_fields_are_strings() -> None:
    result = make_result()
    payload = build_payload(result, "secret", Decimal("1.5"), Decimal("2.0"))
    assert payload is not None
    assert isinstance(payload["price"], str)
    assert isinstance(payload["stop_loss"], str)
    assert isinstance(payload["take_profit"], str)


def test_build_payload_required_fields_present() -> None:
    result = make_result()
    payload = build_payload(result, "secret", Decimal("1.5"), Decimal("2.0"))
    assert payload is not None
    required = {
        "secret", "strategy", "version", "ticker", "side",
        "price", "stop_loss", "take_profit", "timeframe",
        "bar_time", "event_time", "client_signal_id",
    }
    assert required.issubset(payload.keys())


def test_build_payload_strategy_and_version_constants() -> None:
    result = make_result()
    payload = build_payload(result, "secret", Decimal("1.5"), Decimal("2.0"))
    assert payload is not None
    assert payload["strategy"] == "python_atr_generator"
    assert payload["version"] == "0.2b.0"
    assert payload["side"] == "buy"


def test_build_payload_secret_passed_through() -> None:
    result = make_result()
    payload = build_payload(result, "my-secret", Decimal("1.5"), Decimal("2.0"))
    assert payload is not None
    assert payload["secret"] == "my-secret"
