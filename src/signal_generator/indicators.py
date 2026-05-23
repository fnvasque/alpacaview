from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import pandas as pd


@dataclass
class IndicatorResult:
    ticker: str
    timeframe: str
    current_close: Decimal
    current_ema: Decimal
    current_atr: Decimal
    previous_close: Decimal
    previous_ema: Decimal
    bar_time: datetime  # UTC, start of current closed bar
    crossover_detected: bool


def calculate_ema(close: pd.Series, length: int) -> pd.Series:
    return close.ewm(span=length, adjust=False).mean()


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=length).mean()


def compute_indicators(
    df: pd.DataFrame,
    ticker: str,
    timeframe: str,
    ema_length: int,
    atr_length: int,
) -> Optional[IndicatorResult]:
    # row[-1] skipped (may be in-progress), row[-2] = current, row[-3] = previous
    min_required = max(ema_length, atr_length) + 3
    if len(df) < min_required:
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    ema_series = calculate_ema(close, ema_length)
    atr_series = calculate_atr(high, low, close, atr_length)

    curr_atr_val = atr_series.iloc[-2]
    if pd.isna(curr_atr_val):
        return None

    curr_close = Decimal(str(round(float(close.iloc[-2]), 6)))
    curr_ema = Decimal(str(round(float(ema_series.iloc[-2]), 6)))
    curr_atr = Decimal(str(round(float(curr_atr_val), 6)))
    prev_close = Decimal(str(round(float(close.iloc[-3]), 6)))
    prev_ema = Decimal(str(round(float(ema_series.iloc[-3]), 6)))

    bar_ts = df.index[-2]
    if bar_ts.tzinfo is not None:
        bar_time = bar_ts.to_pydatetime().astimezone(timezone.utc)
    else:
        bar_time = bar_ts.to_pydatetime().replace(tzinfo=timezone.utc)

    crossover = (prev_close <= prev_ema) and (curr_close > curr_ema)

    return IndicatorResult(
        ticker=ticker,
        timeframe=timeframe,
        current_close=curr_close,
        current_ema=curr_ema,
        current_atr=curr_atr,
        previous_close=prev_close,
        previous_ema=prev_ema,
        bar_time=bar_time,
        crossover_detected=crossover,
    )
