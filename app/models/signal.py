from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.decision import RiskDecision


class Signal(Base):
    """
    Persisted only for signals that passed all pre-engine checks and were
    evaluated by the Risk Engine. Lifecycle: RECEIVED → RISK_APPROVED | RISK_REJECTED.
    """
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    client_signal_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)
    # Decimal stored as string to preserve precision
    price: Mapped[str] = mapped_column(String, nullable=False)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    bar_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_time_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exchange: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    order_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    stop_loss: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    take_profit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    risk_hint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    position_size: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    decision: Mapped[Optional["RiskDecision"]] = relationship(
        "RiskDecision", back_populates="signal", uselist=False
    )
