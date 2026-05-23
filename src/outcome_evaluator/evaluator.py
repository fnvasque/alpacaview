from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

import pandas as pd


class OutcomeStatus(str, Enum):
    TAKE_PROFIT_HIT = "take_profit_hit"
    STOP_LOSS_HIT = "stop_loss_hit"
    AMBIGUOUS_SAME_BAR = "ambiguous_same_bar"
    TIMEOUT = "timeout"
    PENDING = "pending"


TERMINAL_OUTCOMES: frozenset[str] = frozenset({
    OutcomeStatus.TAKE_PROFIT_HIT.value,
    OutcomeStatus.STOP_LOSS_HIT.value,
    OutcomeStatus.AMBIGUOUS_SAME_BAR.value,
    OutcomeStatus.TIMEOUT.value,
})


@dataclass
class EvaluationResult:
    client_signal_id: str
    ticker: str
    timeframe: str
    outcome: OutcomeStatus
    outcome_bar_time_utc: Optional[datetime] = None
    bars_to_outcome: Optional[int] = None
    pnl_r: Optional[str] = None
    pnl_pct: Optional[str] = None
    max_favorable_excursion: Optional[str] = None
    max_adverse_excursion: Optional[str] = None
    error_message: Optional[str] = None


def evaluate_signal(
    client_signal_id: str,
    ticker: str,
    timeframe: str,
    entry_price: Decimal,
    stop_loss: Decimal,
    take_profit: Decimal,
    bar_time: datetime,
    risk_reward: Optional[Decimal],
    df: pd.DataFrame,
    lookahead_bars: int,
) -> EvaluationResult:
    # Step 1: Normalize bar_time to UTC-aware
    if bar_time.tzinfo is None:
        bar_time = bar_time.replace(tzinfo=timezone.utc)
    bar_ts = pd.Timestamp(bar_time).tz_convert("UTC")

    # Step 2: Normalize df index to UTC-aware
    df_index = df.index
    if df_index.tzinfo is None:
        df_index = df_index.tz_localize("UTC")
    norm_df = df.copy()
    norm_df.index = df_index

    # Step 3: Filter to bars strictly after entry bar
    future_df = norm_df[norm_df.index > bar_ts]
    eval_df = future_df.iloc[:lookahead_bars]

    # Step 4: Edge case — lookahead_bars == 0
    if lookahead_bars == 0:
        return EvaluationResult(
            client_signal_id=client_signal_id,
            ticker=ticker,
            timeframe=timeframe,
            outcome=OutcomeStatus.TIMEOUT,
            bars_to_outcome=0,
        )

    # Step 5: Edge case — no bars in future_df
    if len(future_df) == 0:
        return EvaluationResult(
            client_signal_id=client_signal_id,
            ticker=ticker,
            timeframe=timeframe,
            outcome=OutcomeStatus.PENDING,
            bars_to_outcome=0,
        )

    # Step 6: Iterate through eval_df rows to evaluate outcome
    mfe_val: Optional[Decimal] = None
    mae_val: Optional[Decimal] = None
    outcome: Optional[OutcomeStatus] = None
    outcome_bar_time: Optional[datetime] = None
    bars_to_outcome_val: Optional[int] = None

    for i, (ts, bar) in enumerate(eval_df.iterrows()):
        high = Decimal(str(float(bar["High"])))
        low = Decimal(str(float(bar["Low"])))
        favorable = high - entry_price
        adverse = low - entry_price

        mfe_val = favorable if mfe_val is None else max(mfe_val, favorable)
        mae_val = adverse if mae_val is None else min(mae_val, adverse)

        # Ambiguous check must precede individual checks
        if high >= take_profit and low <= stop_loss:
            outcome = OutcomeStatus.AMBIGUOUS_SAME_BAR
        elif high >= take_profit:
            outcome = OutcomeStatus.TAKE_PROFIT_HIT
        elif low <= stop_loss:
            outcome = OutcomeStatus.STOP_LOSS_HIT

        if outcome is not None:
            if ts.tzinfo is not None:
                outcome_bar_time = ts.to_pydatetime().astimezone(timezone.utc)
            else:
                outcome_bar_time = ts.to_pydatetime().replace(tzinfo=timezone.utc)
            bars_to_outcome_val = i + 1
            break

    # Step 7: Determine final outcome if no event detected
    if outcome is None:
        if len(eval_df) >= lookahead_bars:
            outcome = OutcomeStatus.TIMEOUT
            bars_to_outcome_val = lookahead_bars
            last_ts = eval_df.index[-1]
            if last_ts.tzinfo is not None:
                outcome_bar_time = last_ts.to_pydatetime().astimezone(timezone.utc)
            else:
                outcome_bar_time = last_ts.to_pydatetime().replace(tzinfo=timezone.utc)
        else:
            outcome = OutcomeStatus.PENDING
            bars_to_outcome_val = len(eval_df)
            outcome_bar_time = None

    # Step 8: Compute pnl_r and pnl_pct
    pnl_r_str: Optional[str] = None
    pnl_pct_str: Optional[str] = None

    if outcome == OutcomeStatus.TAKE_PROFIT_HIT:
        rr = risk_reward if risk_reward is not None else (take_profit - entry_price) / (entry_price - stop_loss)
        pnl_r_str = f"{rr:.4f}"
        pnl_pct_str = f"{(take_profit - entry_price) / entry_price:.6f}"
    elif outcome == OutcomeStatus.STOP_LOSS_HIT:
        pnl_r_str = "-1.0000"
        pnl_pct_str = f"{(stop_loss - entry_price) / entry_price:.6f}"

    # Step 9: Format MFE/MAE
    mfe_str = f"{mfe_val:.6f}" if mfe_val is not None else None
    mae_str = f"{mae_val:.6f}" if mae_val is not None else None

    # Step 10: Return
    return EvaluationResult(
        client_signal_id=client_signal_id,
        ticker=ticker,
        timeframe=timeframe,
        outcome=outcome,
        outcome_bar_time_utc=outcome_bar_time,
        bars_to_outcome=bars_to_outcome_val,
        pnl_r=pnl_r_str,
        pnl_pct=pnl_pct_str,
        max_favorable_excursion=mfe_str,
        max_adverse_excursion=mae_str,
    )
