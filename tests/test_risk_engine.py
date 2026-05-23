"""
Pure unit tests for app/risk/engine.py.

No DB, no HTTP, no fixtures beyond simple value objects.
All 6 risk rules (2 enforced + 4 deferred) are covered per the REASONS Canvas requirement.
"""
import ast
import inspect
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import Settings
from app.risk import engine
from app.schemas.enums import RejectionReason, SignalSide
from app.schemas.risk import RiskDecisionResult, RiskSignalSnapshot, TradingContext


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        WEBHOOK_SECRET="test-secret",
        DATABASE_URL="sqlite:///:memory:",
        INITIAL_EQUITY=Decimal("10000"),
        STOP_AFTER_DAILY_TARGET=False,
        KILL_SWITCH=False,
        ALLOWED_TICKERS=["SPY"],
        MAX_DAILY_TRADES=3,
        MAX_DAILY_LOSS_PCT=Decimal("0.0075"),
        MAX_WEEKLY_LOSS_PCT=Decimal("0.025"),
        MAX_CONSECUTIVE_LOSSES=2,
        DAILY_TARGET_PCT=Decimal("0.003"),
    )


@pytest.fixture
def spy_snapshot() -> RiskSignalSnapshot:
    return RiskSignalSnapshot(
        client_signal_id="test-signal-001",
        ticker="SPY",
        side=SignalSide.BUY,
        price=Decimal("450.00"),
    )


def clean_context(**overrides) -> TradingContext:
    defaults = dict(
        et_trading_date=date(2024, 1, 15),
        daily_trade_count=0,
        daily_pnl_pct=Decimal("0"),
        weekly_pnl_pct=Decimal("0"),
        consecutive_losses=0,
        daily_target_would_be_reached=False,
        kill_switch_active=False,
        equity=Decimal("10000"),
    )
    defaults.update(overrides)
    return TradingContext(**defaults)


# ── Enforced: Kill switch ──────────────────────────────────────────────────────

def test_kill_switch_rejects(spy_snapshot, test_settings):
    context = clean_context(kill_switch_active=True)
    result = engine.evaluate(spy_snapshot, context, test_settings)

    assert result.approved is False
    assert result.reason_code == RejectionReason.KILL_SWITCH_ACTIVE
    assert result.is_enforcement_deferred is False


def test_kill_switch_overrides_all_deferred(spy_snapshot, test_settings):
    context = clean_context(
        kill_switch_active=True,
        daily_trade_count=0,
        daily_target_would_be_reached=True,
        daily_pnl_pct=Decimal("-0.01"),
    )
    result = engine.evaluate(spy_snapshot, context, test_settings)

    assert result.approved is False
    assert result.reason_code == RejectionReason.KILL_SWITCH_ACTIVE


# ── Enforced: Max daily trades ─────────────────────────────────────────────────

def test_max_daily_trades_rejects_at_limit(spy_snapshot, test_settings):
    context = clean_context(daily_trade_count=3)
    result = engine.evaluate(spy_snapshot, context, test_settings)

    assert result.approved is False
    assert result.reason_code == RejectionReason.MAX_DAILY_TRADES_REACHED
    assert result.is_enforcement_deferred is False


def test_daily_trades_passes_below_limit(spy_snapshot, test_settings):
    context = clean_context(daily_trade_count=2)
    result = engine.evaluate(spy_snapshot, context, test_settings)

    assert result.approved is True
    assert result.reason_code != RejectionReason.MAX_DAILY_TRADES_REACHED


def test_max_daily_trades_custom_limit(spy_snapshot):
    settings = Settings(
        WEBHOOK_SECRET="test-secret",
        DATABASE_URL="sqlite:///:memory:",
        INITIAL_EQUITY=Decimal("10000"),
        MAX_DAILY_TRADES=1,
        ALLOWED_TICKERS=["SPY"],
    )
    context = clean_context(daily_trade_count=1)
    result = engine.evaluate(spy_snapshot, context, settings)

    assert result.approved is False
    assert result.reason_code == RejectionReason.MAX_DAILY_TRADES_REACHED


# ── Deferred: Daily target ─────────────────────────────────────────────────────

def test_daily_target_deferred(spy_snapshot, test_settings):
    context = clean_context(daily_target_would_be_reached=True)
    result = engine.evaluate(spy_snapshot, context, test_settings)

    assert result.approved is True
    assert result.is_enforcement_deferred is True
    assert result.reason_code == RejectionReason.DAILY_TARGET_REACHED


def test_stop_after_daily_target_setting_has_no_effect_in_v0(spy_snapshot):
    """STOP_AFTER_DAILY_TARGET=True must NOT cause rejection in V0. Engine never reads it."""
    settings = Settings(
        WEBHOOK_SECRET="test-secret",
        DATABASE_URL="sqlite:///:memory:",
        INITIAL_EQUITY=Decimal("10000"),
        STOP_AFTER_DAILY_TARGET=True,  # V1/V2 reserved — must have no effect in V0
        ALLOWED_TICKERS=["SPY"],
    )
    context = clean_context(daily_target_would_be_reached=True)
    result = engine.evaluate(spy_snapshot, context, settings)

    # Must still be approved (deferred), not rejected
    assert result.approved is True
    assert result.is_enforcement_deferred is True
    assert result.reason_code == RejectionReason.DAILY_TARGET_REACHED


# ── Deferred: Daily loss ───────────────────────────────────────────────────────

def test_daily_loss_exceeded_deferred(spy_snapshot, test_settings):
    context = clean_context(daily_pnl_pct=Decimal("-0.01"))
    result = engine.evaluate(spy_snapshot, context, test_settings)

    assert result.approved is True
    assert result.is_enforcement_deferred is True
    assert result.reason_code == RejectionReason.DAILY_LOSS_LIMIT_EXCEEDED


# ── Deferred: Weekly loss ──────────────────────────────────────────────────────

def test_weekly_loss_exceeded_deferred(spy_snapshot, test_settings):
    context = clean_context(weekly_pnl_pct=Decimal("-0.03"))
    result = engine.evaluate(spy_snapshot, context, test_settings)

    assert result.approved is True
    assert result.is_enforcement_deferred is True
    assert result.reason_code == RejectionReason.WEEKLY_LOSS_LIMIT_EXCEEDED


# ── Deferred: Consecutive losses ───────────────────────────────────────────────

def test_consecutive_losses_deferred(spy_snapshot, test_settings):
    context = clean_context(consecutive_losses=2)
    result = engine.evaluate(spy_snapshot, context, test_settings)

    assert result.approved is True
    assert result.is_enforcement_deferred is True
    assert result.reason_code == RejectionReason.CONSECUTIVE_LOSSES_EXCEEDED


# ── All clear ─────────────────────────────────────────────────────────────────

def test_all_clear_approves(spy_snapshot, test_settings):
    context = clean_context()
    result = engine.evaluate(spy_snapshot, context, test_settings)

    assert result.approved is True
    assert result.reason_code is None
    assert result.is_enforcement_deferred is False


# ── Multiple deferred — first wins ────────────────────────────────────────────

def test_multiple_deferred_first_wins(spy_snapshot, test_settings):
    """When multiple deferred conditions trigger, the first evaluated sets reason_code."""
    context = clean_context(
        daily_target_would_be_reached=True,   # evaluated first
        daily_pnl_pct=Decimal("-0.01"),        # also triggered but not reported
    )
    result = engine.evaluate(spy_snapshot, context, test_settings)

    assert result.approved is True
    assert result.is_enforcement_deferred is True
    assert result.reason_code == RejectionReason.DAILY_TARGET_REACHED  # first wins


# ── Engine purity: no ORM imports ────────────────────────────────────────────

def test_engine_has_no_orm_imports():
    """AST-level verification that engine.py does not import ORM or SQLAlchemy."""
    engine_path = Path(__file__).parent.parent / "app" / "risk" / "engine.py"
    source = engine_path.read_text()

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("app.models"), (
                    f"engine.py must not import from app.models — found: from {node.module}"
                )
                assert "sqlalchemy" not in node.module, (
                    f"engine.py must not import sqlalchemy — found: from {node.module}"
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "sqlalchemy" not in alias.name, (
                        f"engine.py must not import sqlalchemy — found: import {alias.name}"
                    )
