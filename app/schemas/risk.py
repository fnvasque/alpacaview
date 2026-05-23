from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.enums import RejectionReason, SignalSide


class TradingContext(BaseModel):
    """
    Immutable snapshot of trading state passed to the Risk Engine.
    Assembled from DB immediately before engine evaluation. Never persisted.

    In V0 all PnL fields are zero — no fills exist to compute realized PnL.
    """
    et_trading_date: date
    daily_trade_count: int
    daily_pnl_pct: Decimal = Decimal("0")
    weekly_pnl_pct: Decimal = Decimal("0")
    consecutive_losses: int = 0
    daily_target_would_be_reached: bool = False
    kill_switch_active: bool = False
    equity: Decimal

    model_config = ConfigDict(frozen=True)


class RiskSignalSnapshot(BaseModel):
    """
    Immutable value object passed to engine.evaluate().
    Extracted from the persisted Signal ORM object by the service layer.
    Isolates engine.py from ORM model imports.
    """
    client_signal_id: str
    ticker: str
    side: SignalSide
    price: Decimal
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None

    model_config = ConfigDict(frozen=True)


class RiskDecisionResult(BaseModel):
    """
    Pure return value from engine.evaluate(). Not an ORM model.
    Mapped to a RiskDecision ORM row by the service layer.

    When is_enforcement_deferred=True: approved=True but a limit would have been
    triggered in V1/V2. The reason_code is informative only.
    approved=True means risk-approved for observability only. V0 does not execute orders.
    """
    approved: bool
    reason_code: Optional[RejectionReason] = None
    reason_detail: Optional[str] = None
    is_enforcement_deferred: bool = False

    model_config = ConfigDict(frozen=True)
