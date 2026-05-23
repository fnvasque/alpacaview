from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.signal import Signal


class RiskDecision(Base):
    """
    Persisted outcome of Risk Engine evaluation. Always 1:1 with Signal.

    When is_enforcement_deferred=True: approved=True but a deferred limit was
    triggered. reason_code is informative. V1/V2 will enforce these limits.
    """
    __tablename__ = "risk_decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    signal_id: Mapped[str] = mapped_column(
        String, ForeignKey("signals.id"), nullable=False, index=True
    )
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Populated even for approved+deferred decisions — informative reason_code
    reason_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reason_detail: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # True when a limit would be triggered but enforcement is deferred to V1/V2
    is_enforcement_deferred: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    signal: Mapped["Signal"] = relationship("Signal", back_populates="decision")
