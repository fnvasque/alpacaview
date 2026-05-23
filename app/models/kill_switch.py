from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KillSwitchState(Base):
    """
    Singleton row (id=1) for the global kill switch.
    When active=True, the Risk Engine rejects all signals regardless of other limits.
    Falls back to KILL_SWITCH env var when no DB row exists.
    """
    __tablename__ = "kill_switch_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activated_at_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
