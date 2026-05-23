import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.repositories import webhook_event_repo
from app.schemas.enums import RejectionReason, WebhookEventType
from app.services import signal_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post("/signal")
async def receive_signal(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    try:
        raw_payload = await request.json()
    except Exception:
        raw_bytes = await request.body()
        body_preview = raw_bytes[:500].decode("utf-8", errors="replace")
        webhook_event_repo.create_event(
            db,
            WebhookEventType.SCHEMA_INVALID,
            RejectionReason.SCHEMA_INVALID,
            raw_payload_masked=body_preview,
            reason_detail="Invalid JSON body",
        )
        log.warning(
            "pipeline_stage",
            extra={"stage": "json_parse", "result": "failed"},
        )
        return Response(
            content='{"approved":false,"reason_code":"schema_invalid","reason_detail":"invalid json body"}',
            status_code=400,
            media_type="application/json",
        )

    webhook_response, status_code = signal_service.process_raw_payload(raw_payload, db, settings)
    return Response(
        content=webhook_response.model_dump_json(),
        status_code=status_code,
        media_type="application/json",
    )
