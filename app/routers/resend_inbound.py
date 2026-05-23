import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.integrations.resend_client import ResendClient, get_resend_client
from app.services import resend_inbound_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations/resend", tags=["integrations"])


@router.post("/inbound")
async def receive_resend_inbound(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    resend_client: ResendClient = Depends(get_resend_client),
) -> Response:
    try:
        raw_payload = await request.json()
    except Exception:
        log.warning(
            "resend_json_parse",
            extra={"stage": "resend_json_parse", "result": "failed"},
        )
        return Response(
            content='{"detail":"invalid json body"}',
            status_code=400,
            media_type="application/json",
        )

    body, status_code = await resend_inbound_service.process_resend_event(
        raw_payload, db, settings, resend_client
    )
    return Response(content=body, status_code=status_code, media_type="application/json")
