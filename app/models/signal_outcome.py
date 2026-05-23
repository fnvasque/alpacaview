from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"
    __table_args__ = (UniqueConstraint("client_signal_id", name="uq_signal_outcomes_client_signal_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    client_signal_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    entry_price: Mapped[str] = mapped_column(String, nullable=False)
    stop_loss: Mapped[str] = mapped_column(String, nullable=False)
    take_profit: Mapped[str] = mapped_column(String, nullable=False)
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    forward_test_run_status: Mapped[str] = mapped_column(String, nullable=False)
    is_dry_run_source: Mapped[bool] = mapped_column(Boolean, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    outcome_bar_time_utc: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    bars_to_outcome: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pnl_r: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    pnl_pct: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    max_favorable_excursion: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    max_adverse_excursion: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    evaluated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
