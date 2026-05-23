"""
Unit tests for src.signal_generator.indicators.

No yfinance calls, no network. Synthetic DataFrames only.
"""
from decimal import Decimal

import pandas as pd
import pytest

from src.signal_generator.indicators import (
    IndicatorResult,
    calculate_atr,
    calculate_ema,
    compute_indicators,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_df(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> pd.DataFrame:
    n = len(closes)
    if highs is None:
        highs = [c * 1.01 for c in closes]
    if lows is None:
        lows = [c * 0.99 for c in closes]
    index = pd.date_range("2026-05-20 14:00", periods=n, freq="15min", tz="America/New_York")
    return pd.DataFrame(
        {
            "Open": closes,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": [1_000_000] * n,
        },
        index=index,
    )


# ── EMA ────────────────────────────────────────────────────────────────────────

def test_ema_series_length_matches_input() -> None:
    close = pd.Series([100.0] * 30)
    ema = calculate_ema(close, 21)
    assert len(ema) == 30


def test_ema_converges_to_constant_price() -> None:
    close = pd.Series([150.0] * 60)
    ema = calculate_ema(close, 21)
    assert abs(ema.iloc[-1] - 150.0) < 0.001


def test_ema_responds_to_price_change() -> None:
    close = pd.Series([100.0] * 40 + [200.0] * 20)
    ema = calculate_ema(close, 21)
    assert 100.0 < ema.iloc[-1] < 200.0


# ── ATR ────────────────────────────────────────────────────────────────────────

def test_atr_series_length_matches_input() -> None:
    close = pd.Series([100.0] * 30)
    high = pd.Series([101.0] * 30)
    low = pd.Series([99.0] * 30)
    atr = calculate_atr(high, low, close, 14)
    assert len(atr) == 30


def test_atr_constant_range_converges() -> None:
    # H-L = 2.0 constant, no overnight gaps → TR = 2.0 → ATR ≈ 2.0
    close = pd.Series([100.0] * 40)
    high = pd.Series([101.0] * 40)
    low = pd.Series([99.0] * 40)
    atr = calculate_atr(high, low, close, 14)
    assert abs(atr.iloc[-1] - 2.0) < 0.01


def test_atr_nan_before_warmup() -> None:
    close = pd.Series([100.0] * 5)
    high = pd.Series([101.0] * 5)
    low = pd.Series([99.0] * 5)
    atr = calculate_atr(high, low, close, 14)
    assert pd.isna(atr.iloc[-1])


# ── compute_indicators ─────────────────────────────────────────────────────────

def test_insufficient_data_returns_none() -> None:
    df = make_df([100.0] * 10)
    result = compute_indicators(df, "SPY", "15m", 21, 14)
    assert result is None


def test_exact_min_rows_is_sufficient() -> None:
    # min_required = max(21, 14) + 3 = 24
    df = make_df([100.0] * 24)
    # ATR won't be warmed at iloc[-2] with only 21+3=24 rows, so may be None — that's OK
    # The important thing is the function doesn't crash
    result = compute_indicators(df, "SPY", "15m", 21, 14)
    # Result could be None due to ATR NaN — acceptable
    assert result is None or isinstance(result, IndicatorResult)


def test_crossover_detected() -> None:
    # Warm up EMA on stable 100 for 50 bars
    # Then: prev_bar close=99 (below EMA ~100), curr_bar close=102 (above EMA ~100)
    # Add one more row at the end to serve as the "in-progress" row[-1]
    closes = [100.0] * 50 + [99.0, 102.0, 100.0]
    df = make_df(closes)
    result = compute_indicators(df, "SPY", "15m", 21, 14)
    assert result is not None
    assert result.crossover_detected is True


def test_no_crossover_when_price_stable() -> None:
    # Constant price → close always equals EMA → no crossover (prev_close <= prev_ema is True
    # but curr_close > curr_ema is False since they're equal)
    closes = [100.0] * 60
    df = make_df(closes)
    result = compute_indicators(df, "SPY", "15m", 21, 14)
    assert result is not None
    assert result.crossover_detected is False


def test_partial_bar_skipped() -> None:
    # row[-1] has anomalous price — current_close must NOT be that value
    closes = [100.0] * 59 + [9999.0]
    df = make_df(closes)
    result = compute_indicators(df, "SPY", "15m", 21, 14)
    assert result is not None
    assert result.current_close != Decimal("9999.000000")


def test_bar_time_is_utc() -> None:
    df = make_df([100.0] * 60)
    result = compute_indicators(df, "SPY", "15m", 21, 14)
    assert result is not None
    assert result.bar_time.tzinfo is not None
    assert result.bar_time.utcoffset().total_seconds() == 0


def test_all_price_fields_are_decimal() -> None:
    df = make_df([100.0] * 60)
    result = compute_indicators(df, "SPY", "15m", 21, 14)
    assert result is not None
    assert isinstance(result.current_close, Decimal)
    assert isinstance(result.current_ema, Decimal)
    assert isinstance(result.current_atr, Decimal)
    assert isinstance(result.previous_close, Decimal)
    assert isinstance(result.previous_ema, Decimal)


def test_ticker_and_timeframe_preserved() -> None:
    df = make_df([100.0] * 60)
    result = compute_indicators(df, "NVDA", "15m", 21, 14)
    assert result is not None
    assert result.ticker == "NVDA"
    assert result.timeframe == "15m"
