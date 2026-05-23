from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WebhookEvent(Base):
    """
    Audit log for all pre-engine rejections and invalid JSON events.
    No foreign key to signals — exists independently.

    Covers: AUTH_FAILED, SCHEMA_INVALID, UNSUPPORTED_SIDE,
    UNSUPPORTED_ASSET_CLASS, DUPLICATE_SIGNAL.
    """
    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    reason_code: Mapped[str] = mapped_column(String, nullable=False)
    reason_detail: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Extracted from raw payload if available; None when field is missing
    client_signal_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Pre-masked by caller: secret replaced with "***", or raw body preview for JSON errors
    raw_payload_masked: Mapped[str] = mapped_column(String, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
