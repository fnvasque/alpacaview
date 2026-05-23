from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ForwardTestRun(Base):
    __tablename__ = "forward_test_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String, nullable=False)
    period: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    is_dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bar_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    client_signal_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    price: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    stop_loss: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    take_profit: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    risk_reward: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    backend_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    backend_signal_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    backend_approved: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    backend_reason_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    backend_reason_detail: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
