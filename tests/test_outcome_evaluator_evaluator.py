"""
Unit tests for src.outcome_evaluator.evaluator.evaluate_signal().

No network, no DB. All DataFrames injected as synthetic pandas DataFrames.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import pandas as pd
import pytest

from src.outcome_evaluator.evaluator import (
    EvaluationResult,
    OutcomeStatus,
    evaluate_signal,
)

_UTC = timezone.utc
BASE_BAR_TIME = datetime(2026, 5, 20, 14, 30, 0, tzinfo=_UTC)
_BASE_ENTRY = Decimal("450.0000")
_BASE_SL = Decimal("447.0000")
_BASE_TP = Decimal("456.0000")
_BASE_RR = Decimal("2.0000")


def make_df(rows: list[dict]) -> pd.DataFrame:
    """Build a UTC-aware DatetimeIndex DataFrame with High, Low, Close columns."""
    index = pd.DatetimeIndex(
        [r["ts"] for r in rows], tz="UTC"
    )
    data = {
        "High": [r["high"] for r in rows],
        "Low": [r["low"] for r in rows],
        "Close": [r.get("close", r["low"]) for r in rows],
    }
    return pd.DataFrame(data, index=index)


def make_signal(**overrides) -> dict:
    defaults = {
        "entry_price": _BASE_ENTRY,
        "stop_loss": _BASE_SL,
        "take_profit": _BASE_TP,
        "risk_reward": _BASE_RR,
        "bar_time": BASE_BAR_TIME,
    }
    defaults.update(overrides)
    return defaults


def _bar_after(minutes: int) -> datetime:
    from datetime import timedelta
    return BASE_BAR_TIME + timedelta(minutes=minutes * 15)


def _eval(df: pd.DataFrame, lookahead: int = 26, **sig_overrides) -> EvaluationResult:
    sig = make_signal(**sig_overrides)
    return evaluate_signal(
        client_signal_id="test:signal:id",
        ticker="SPY",
        timeframe="15m",
        entry_price=sig["entry_price"],
        stop_loss=sig["stop_loss"],
        take_profit=sig["take_profit"],
        bar_time=sig["bar_time"],
        risk_reward=sig["risk_reward"],
        df=df,
        lookahead_bars=lookahead,
    )


# ── Basic outcomes ─────────────────────────────────────────────────────────────

def test_take_profit_hit_on_first_bar() -> None:
    df = make_df([{"ts": _bar_after(1), "high": 456.50, "low": 449.0}])
    result = _eval(df)
    assert result.outcome == OutcomeStatus.TAKE_PROFIT_HIT
    assert result.bars_to_outcome == 1


def test_stop_loss_hit_on_first_bar() -> None:
    df = make_df([{"ts": _bar_after(1), "high": 451.0, "low": 446.50}])
    result = _eval(df)
    assert result.outcome == OutcomeStatus.STOP_LOSS_HIT
    assert result.bars_to_outcome == 1


def test_ambiguous_same_bar() -> None:
    df = make_df([{"ts": _bar_after(1), "high": 456.50, "low": 446.50}])
    result = _eval(df)
    assert result.outcome == OutcomeStatus.AMBIGUOUS_SAME_BAR
    assert result.pnl_r is None
    assert result.pnl_pct is None


def test_take_profit_hit_on_third_bar() -> None:
    df = make_df([
        {"ts": _bar_after(1), "high": 451.0, "low": 449.0},
        {"ts": _bar_after(2), "high": 452.0, "low": 449.5},
        {"ts": _bar_after(3), "high": 456.50, "low": 451.0},
    ])
    result = _eval(df)
    assert result.outcome == OutcomeStatus.TAKE_PROFIT_HIT
    assert result.bars_to_outcome == 3


def test_timeout_when_lookahead_exhausted() -> None:
    rows = [{"ts": _bar_after(i + 1), "high": 451.0, "low": 449.0} for i in range(26)]
    df = make_df(rows)
    result = _eval(df, lookahead=26)
    assert result.outcome == OutcomeStatus.TIMEOUT
    assert result.bars_to_outcome == 26
    assert result.outcome_bar_time_utc is not None


def test_pending_when_insufficient_bars() -> None:
    rows = [{"ts": _bar_after(i + 1), "high": 451.0, "low": 449.0} for i in range(5)]
    df = make_df(rows)
    result = _eval(df, lookahead=26)
    assert result.outcome == OutcomeStatus.PENDING
    assert result.bars_to_outcome == 5
    assert result.outcome_bar_time_utc is None


def test_empty_dataframe_returns_pending() -> None:
    df = make_df([])
    result = _eval(df, lookahead=26)
    assert result.outcome == OutcomeStatus.PENDING
    assert result.bars_to_outcome == 0


def test_lookahead_zero_returns_timeout() -> None:
    df = make_df([{"ts": _bar_after(1), "high": 460.0, "low": 440.0}])
    result = _eval(df, lookahead=0)
    assert result.outcome == OutcomeStatus.TIMEOUT
    assert result.bars_to_outcome == 0


# ── Entry bar exclusion ────────────────────────────────────────────────────────

def test_entry_bar_excluded() -> None:
    # Entry bar itself (same timestamp) has high above tp — must not trigger
    df = make_df([
        {"ts": BASE_BAR_TIME, "high": 456.50, "low": 449.0},  # entry bar — excluded
        {"ts": _bar_after(1), "high": 451.0, "low": 449.0},   # only post-entry bar
    ])
    result = _eval(df, lookahead=26)
    # Only one post-entry bar available, no hit → pending
    assert result.outcome == OutcomeStatus.PENDING
    assert result.bars_to_outcome == 1


# ── PnL calculations ───────────────────────────────────────────────────────────

def test_pnl_r_take_profit_hit() -> None:
    df = make_df([{"ts": _bar_after(1), "high": 456.50, "low": 449.0}])
    result = _eval(df)
    assert result.pnl_r == "2.0000"


def test_pnl_r_stop_loss_hit() -> None:
    df = make_df([{"ts": _bar_after(1), "high": 451.0, "low": 446.50}])
    result = _eval(df)
    assert result.pnl_r == "-1.0000"


def test_pnl_pct_take_profit_hit() -> None:
    # (456 - 450) / 450 = 0.013333...
    df = make_df([{"ts": _bar_after(1), "high": 456.50, "low": 449.0}])
    result = _eval(df)
    assert result.pnl_pct is not None
    assert result.pnl_pct.startswith("0.013333")


def test_pnl_pct_stop_loss_hit() -> None:
    # (447 - 450) / 450 = -0.006667...
    df = make_df([{"ts": _bar_after(1), "high": 451.0, "low": 446.50}])
    result = _eval(df)
    assert result.pnl_pct is not None
    assert result.pnl_pct.startswith("-0.006667")


def test_pnl_null_for_ambiguous() -> None:
    df = make_df([{"ts": _bar_after(1), "high": 456.50, "low": 446.50}])
    result = _eval(df)
    assert result.pnl_r is None
    assert result.pnl_pct is None


def test_pnl_null_for_timeout() -> None:
    rows = [{"ts": _bar_after(i + 1), "high": 451.0, "low": 449.0} for i in range(26)]
    df = make_df(rows)
    result = _eval(df, lookahead=26)
    assert result.pnl_r is None
    assert result.pnl_pct is None


def test_pnl_null_for_pending() -> None:
    rows = [{"ts": _bar_after(i + 1), "high": 451.0, "low": 449.0} for i in range(5)]
    df = make_df(rows)
    result = _eval(df, lookahead=26)
    assert result.pnl_r is None
    assert result.pnl_pct is None


# ── MFE / MAE ─────────────────────────────────────────────────────────────────

def test_mfe_is_max_high_minus_entry() -> None:
    # highs: 451, 453, 452 — max favorable = 453 - 450 = 3.0
    df = make_df([
        {"ts": _bar_after(1), "high": 451.0, "low": 449.0},
        {"ts": _bar_after(2), "high": 453.0, "low": 449.0},
        {"ts": _bar_after(3), "high": 452.0, "low": 449.0},
    ])
    result = _eval(df, lookahead=26)
    assert result.max_favorable_excursion == "3.000000"


def test_mae_is_min_low_minus_entry() -> None:
    # lows: 449, 448, 449 — min adverse = 448 - 450 = -2.0
    df = make_df([
        {"ts": _bar_after(1), "high": 451.0, "low": 449.0},
        {"ts": _bar_after(2), "high": 451.0, "low": 448.0},
        {"ts": _bar_after(3), "high": 451.0, "low": 449.0},
    ])
    result = _eval(df, lookahead=26)
    assert result.max_adverse_excursion == "-2.000000"


def test_mfe_mae_null_when_no_bars() -> None:
    df = make_df([])
    result = _eval(df, lookahead=26)
    assert result.max_favorable_excursion is None
    assert result.max_adverse_excursion is None


def test_mfe_mae_populated_for_pending() -> None:
    # highs stay below tp (456), lows stay above sl (447)
    rows = [{"ts": _bar_after(i + 1), "high": 451.0 + i, "low": 449.5 - i * 0.5} for i in range(5)]
    df = make_df(rows)
    result = _eval(df, lookahead=26)
    assert result.outcome == OutcomeStatus.PENDING
    assert result.max_favorable_excursion is not None
    assert result.max_adverse_excursion is not None


def test_mfe_stops_at_outcome_bar() -> None:
    # Bar 1: neutral. Bar 2: tp hit. Bar 3 (never evaluated): very high
    df = make_df([
        {"ts": _bar_after(1), "high": 451.0, "low": 449.0},
        {"ts": _bar_after(2), "high": 456.50, "low": 449.0},
        {"ts": _bar_after(3), "high": 460.0, "low": 445.0},
    ])
    result = _eval(df, lookahead=26)
    assert result.outcome == OutcomeStatus.TAKE_PROFIT_HIT
    assert result.bars_to_outcome == 2
    # MFE computed up to bar 2: max(451-450, 456.5-450) = 6.5
    assert result.max_favorable_excursion == "6.500000"


# ── Edge cases ─────────────────────────────────────────────────────────────────

def test_timezone_naive_df_handled() -> None:
    # Naive-indexed df must not raise TypeError
    naive_ts = datetime(2026, 5, 20, 14, 45, 0)
    df = pd.DataFrame(
        {"High": [451.0], "Low": [449.0], "Close": [450.0]},
        index=pd.DatetimeIndex([naive_ts]),
    )
    result = _eval(df, lookahead=26)
    # Should return PENDING (no hit) without error
    assert result.outcome in (OutcomeStatus.PENDING, OutcomeStatus.TIMEOUT)


def test_risk_reward_fallback_recomputed() -> None:
    # risk_reward=None → recompute from (tp-price)/(price-sl) = 6/3 = 2.0
    df = make_df([{"ts": _bar_after(1), "high": 456.50, "low": 449.0}])
    result = _eval(df, risk_reward=None)
    assert result.pnl_r == "2.0000"
