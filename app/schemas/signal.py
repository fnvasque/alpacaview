from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.enums import SignalSide, SignalStatus


class WebhookSignalRequest(BaseModel):
    """
    TradingView webhook payload. Both BUY and SELL are schema-valid.
    SELL is rejected at the service layer, not the schema layer.
    """
    secret: str
    strategy: str
    version: str
    ticker: str
    side: SignalSide
    price: Decimal
    timeframe: str
    bar_time: datetime
    event_time: datetime
    client_signal_id: str
    exchange: Optional[str] = None
    order_id: Optional[str] = None
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    risk_hint: Optional[Decimal] = None
    position_size: Optional[Decimal] = None

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("ticker", mode="before")
    @classmethod
    def uppercase_ticker(cls, v: str) -> str:
        return v.upper() if isinstance(v, str) else v

    @field_validator("bar_time", "event_time", mode="after")
    @classmethod
    def normalize_to_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @field_validator("client_signal_id", mode="after")
    @classmethod
    def client_signal_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("client_signal_id must not be empty")
        return v


class WebhookResponse(BaseModel):
    """
    Unified response for all webhook outcomes.
    signal_id is None for pre-engine rejections (WebhookEvent-only paths).
    approved=True means risk-approved for observability only. V0 does not execute orders.
    """
    signal_id: Optional[str] = None
    client_signal_id: Optional[str] = None
    status: str
    approved: bool
    reason_code: Optional[str] = None
    reason_detail: Optional[str] = None
    received_at: datetime

    model_config = ConfigDict(use_enum_values=True)
