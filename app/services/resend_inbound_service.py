import json
import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.resend_client import ResendClient, ResendClientError, ResendEmailContent
from app.services import signal_service

log = logging.getLogger(__name__)


async def process_resend_event(
    event_payload: dict,
    db: Session,
    settings: Settings,
    resend_client: ResendClient,
) -> tuple[str, int]:
    # 1. Feature flag gate
    if not settings.RESEND_RECEIVING_ENABLED:
        return '{"detail":"not_found"}', 404

    # 2. Key gate
    if settings.RESEND_API_KEY is None:
        return (
            '{"reason_code":"resend_not_configured","detail":"Resend adapter is enabled but RESEND_API_KEY is not set"}',
            503,
        )

    # 3. Event type gate — evaluated before any strict schema validation
    event_type = event_payload.get("type")
    if event_type != "email.received":
        log.info(
            "resend_event_ignored",
            extra={"stage": "resend_event_ignored", "event_type": event_type},
        )
        return '{"status":"ignored","reason_code":"unsupported_resend_event_type"}', 200

    # 4. Extract email_id — accept both data.email_id and data.id for compatibility
    data = event_payload.get("data") or {}
    email_id = data.get("email_id") or data.get("id")
    if not email_id:
        return '{"detail":"invalid_resend_event"}', 422

    # 5. Fetch email
    try:
        content = await resend_client.fetch_email(email_id)
    except ResendClientError:
        log.warning(
            "resend_fetch_failed",
            extra={"stage": "resend_fetch_failed", "email_id": email_id},
        )
        return '{"detail":"upstream_error"}', 502

    # 6. Body size gate
    if (
        len(content.text or "") > settings.RESEND_MAX_EMAIL_BODY_CHARS
        or len(content.html or "") > settings.RESEND_MAX_EMAIL_BODY_CHARS
    ):
        log.warning(
            "resend_body_too_large",
            extra={"stage": "resend_body_too_large", "email_id": email_id},
        )
        return (
            '{"reason_code":"email_body_too_large","detail":"email body exceeds configured limit"}',
            413,
        )

    # 7. JSON extraction
    raw_payload = _extract_first_json(content)
    if raw_payload is None:
        log.warning(
            "resend_no_json",
            extra={"stage": "resend_no_json", "email_id": email_id},
        )
        return '{"detail":"no_json_in_email"}', 422

    # 8. Delegate and return
    webhook_response, status_code = signal_service.process_raw_payload(raw_payload, db, settings)
    # Translate duplicate 409 → 200 so Resend does not retry the same email.
    # The body is preserved unchanged; audit records are already written by the pipeline.
    if status_code == 409 and webhook_response.reason_code == "duplicate_signal":
        status_code = 200
    return webhook_response.model_dump_json(), status_code


def _extract_first_json(content: ResendEmailContent) -> Optional[dict]:
    result = _parse_first_json_from_text(content.text or "")
    if result is None and content.html:
        cleaned = re.sub(r"<[^>]+>", "", content.html)
        result = _parse_first_json_from_text(cleaned)
    return result


def _parse_first_json_from_text(text: str) -> Optional[dict]:
    idx = text.find("{")
    if idx == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, idx)
        if isinstance(obj, dict):
            return obj
        return None
    except json.JSONDecodeError:
        return None
