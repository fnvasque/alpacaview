import json
from typing import Optional

from sqlalchemy.orm import Session

from app.models.webhook_event import WebhookEvent
from app.schemas.enums import RejectionReason, WebhookEventType


def mask_payload(raw_payload: dict) -> str:
    """
    Replace the secret field with *** and return a JSON string.
    Call this before any logging or audit write. Never log the raw secret.
    """
    return json.dumps({**raw_payload, "secret": "***"})


def create_event(
    db: Session,
    event_type: WebhookEventType,
    reason_code: RejectionReason,
    raw_payload_masked: str,
    client_signal_id: Optional[str] = None,
    reason_detail: Optional[str] = None,
) -> WebhookEvent:
    """
    Insert a WebhookEvent audit record and commit immediately.
    Commits independently so the audit record persists even if the main
    transaction later rolls back.

    raw_payload_masked must be pre-masked by the caller (secret replaced with ***)
    or a safe body preview for JSON parse errors.
    """
    event = WebhookEvent(
        event_type=event_type.value,
        reason_code=reason_code.value,
        reason_detail=reason_detail,
        client_signal_id=client_signal_id,
        raw_payload_masked=raw_payload_masked,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event
