import hmac
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import decision_repo, kill_switch_repo, signal_repo, webhook_event_repo
from app.risk import context as context_builder
from app.risk import engine
from app.services import signal_quality
from app.schemas.enums import (
    RejectionReason,
    SignalSide,
    SignalStatus,
    WebhookEventType,
)
from app.schemas.risk import RiskDecisionResult, RiskSignalSnapshot
from app.schemas.signal import WebhookResponse, WebhookSignalRequest

log = logging.getLogger(__name__)


def process_raw_payload(
    raw_payload: dict,
    db: Session,
    settings: Settings,
) -> tuple[WebhookResponse, int]:
    """
    Execute the complete signal processing pipeline for one inbound payload.

    Steps 1–5 produce WebhookEvent records (no Signal created).
    Steps 6–10 produce a Signal + RiskDecision pair.

    Returns (WebhookResponse, http_status_code).
    approved=True means risk-approved for observability only. V0 does not execute orders.
    """
    received_at = datetime.now(timezone.utc)

    # ── Step 1: Secret validation ───────────────────────────────────────────
    incoming_secret = str(raw_payload.get("secret", ""))
    if not hmac.compare_digest(incoming_secret.encode(), settings.WEBHOOK_SECRET.encode()):
        masked = webhook_event_repo.mask_payload(raw_payload)
        webhook_event_repo.create_event(
            db,
            WebhookEventType.AUTH_FAILED,
            RejectionReason.INVALID_SECRET,
            masked,
        )
        log.warning(
            "pipeline_stage",
            extra={"stage": "secret_validation", "result": "failed"},
        )
        return _rejection_response(None, None, RejectionReason.INVALID_SECRET, received_at), 401

    # ── Step 2: Schema validation ───────────────────────────────────────────
    try:
        parsed = WebhookSignalRequest.model_validate(raw_payload)
    except ValidationError as exc:
        masked = webhook_event_repo.mask_payload(raw_payload)
        webhook_event_repo.create_event(
            db,
            WebhookEventType.SCHEMA_INVALID,
            RejectionReason.SCHEMA_INVALID,
            masked,
            client_signal_id=raw_payload.get("client_signal_id"),
            reason_detail=str(exc),
        )
        log.warning(
            "pipeline_stage",
            extra={
                "stage": "schema_validation",
                "result": "failed",
                "client_signal_id": raw_payload.get("client_signal_id"),
            },
        )
        return (
            _rejection_response(
                None,
                raw_payload.get("client_signal_id"),
                RejectionReason.SCHEMA_INVALID,
                received_at,
                reason_detail=str(exc),
            ),
            422,
        )

    # ── Step 3: Side validation ─────────────────────────────────────────────
    if parsed.side != SignalSide.BUY:
        masked = webhook_event_repo.mask_payload(raw_payload)
        webhook_event_repo.create_event(
            db,
            WebhookEventType.UNSUPPORTED_SIDE,
            RejectionReason.UNSUPPORTED_SIDE,
            masked,
            client_signal_id=parsed.client_signal_id,
            reason_detail=f"side={parsed.side.value} not supported in V0",
        )
        log.warning(
            "pipeline_stage",
            extra={
                "stage": "side_validation",
                "result": "failed",
                "side": parsed.side.value,
                "client_signal_id": parsed.client_signal_id,
            },
        )
        return (
            _rejection_response(
                None,
                parsed.client_signal_id,
                RejectionReason.UNSUPPORTED_SIDE,
                received_at,
            ),
            422,
        )

    # ── Step 4: Asset class validation ──────────────────────────────────────
    if _is_unsupported_asset(parsed.ticker, settings):
        masked = webhook_event_repo.mask_payload(raw_payload)
        webhook_event_repo.create_event(
            db,
            WebhookEventType.UNSUPPORTED_ASSET_CLASS,
            RejectionReason.UNSUPPORTED_ASSET_CLASS,
            masked,
            client_signal_id=parsed.client_signal_id,
            reason_detail=f"ticker={parsed.ticker}",
        )
        log.warning(
            "pipeline_stage",
            extra={
                "stage": "asset_validation",
                "result": "failed",
                "ticker": parsed.ticker,
                "client_signal_id": parsed.client_signal_id,
            },
        )
        return (
            _rejection_response(
                None,
                parsed.client_signal_id,
                RejectionReason.UNSUPPORTED_ASSET_CLASS,
                received_at,
            ),
            422,
        )

    # ── Step 4.5: Signal quality validation ─────────────────────────────────
    quality_failure = signal_quality.validate_signal_quality(parsed, settings, received_at)
    if quality_failure is not None:
        reason_code, detail = quality_failure
        masked = webhook_event_repo.mask_payload(raw_payload)
        webhook_event_repo.create_event(
            db,
            WebhookEventType.SIGNAL_QUALITY_REJECTED,
            reason_code,
            masked,
            client_signal_id=parsed.client_signal_id,
            reason_detail=detail,
        )
        log.warning(
            "pipeline_stage",
            extra={
                "stage": "signal_quality_check",
                "result": "failed",
                "reason_code": reason_code.value,
                "client_signal_id": parsed.client_signal_id,
            },
        )
        return (
            _rejection_response(None, parsed.client_signal_id, reason_code, received_at, reason_detail=detail),
            422,
        )

    # ── Step 5: Idempotency check ───────────────────────────────────────────
    if signal_repo.get_by_client_signal_id(db, parsed.client_signal_id):
        masked = webhook_event_repo.mask_payload(raw_payload)
        webhook_event_repo.create_event(
            db,
            WebhookEventType.DUPLICATE_SIGNAL,
            RejectionReason.DUPLICATE_SIGNAL,
            masked,
            client_signal_id=parsed.client_signal_id,
        )
        log.warning(
            "pipeline_stage",
            extra={
                "stage": "idempotency_check",
                "result": "duplicate",
                "client_signal_id": parsed.client_signal_id,
            },
        )
        return (
            _rejection_response(
                None,
                parsed.client_signal_id,
                RejectionReason.DUPLICATE_SIGNAL,
                received_at,
            ),
            409,
        )

    # ── Step 6: Persist Signal (RECEIVED) ───────────────────────────────────
    try:
        signal = signal_repo.create(db, _map_to_signal_dict(parsed))
    except IntegrityError:
        db.rollback()
        # Race condition: another request inserted the same client_signal_id
        masked = webhook_event_repo.mask_payload(raw_payload)
        webhook_event_repo.create_event(
            db,
            WebhookEventType.DUPLICATE_SIGNAL,
            RejectionReason.DUPLICATE_SIGNAL,
            masked,
            client_signal_id=parsed.client_signal_id,
            reason_detail="race_condition_integrity_error",
        )
        return (
            _rejection_response(
                None,
                parsed.client_signal_id,
                RejectionReason.DUPLICATE_SIGNAL,
                received_at,
            ),
            409,
        )

    log.info(
        "pipeline_stage",
        extra={
            "stage": "signal_persisted",
            "result": "received",
            "signal_id": signal.id,
            "client_signal_id": signal.client_signal_id,
            "ticker": signal.ticker,
        },
    )

    # ── Step 7: Build TradingContext ─────────────────────────────────────────
    try:
        context = context_builder.build_trading_context(db, settings)
    except Exception:
        db.rollback()
        log.exception("context_build_failed", extra={"signal_id": signal.id})
        masked = webhook_event_repo.mask_payload(raw_payload)
        webhook_event_repo.create_event(
            db,
            WebhookEventType.INTERNAL_ERROR,
            RejectionReason.INTERNAL_ERROR,
            masked,
            client_signal_id=parsed.client_signal_id,
            reason_detail="context_build_failed",
        )
        return _error_response(received_at), 500

    # ── Step 8: Build RiskSignalSnapshot (isolates engine from ORM) ──────────
    snapshot = RiskSignalSnapshot(
        client_signal_id=signal.client_signal_id,
        ticker=signal.ticker,
        side=SignalSide(signal.side),
        price=Decimal(signal.price),
        stop_loss=Decimal(signal.stop_loss) if signal.stop_loss else None,
        take_profit=Decimal(signal.take_profit) if signal.take_profit else None,
    )

    # ── Step 9: Risk Engine evaluation ──────────────────────────────────────
    result: RiskDecisionResult = engine.evaluate(snapshot, context, settings)

    # ── Step 10: Atomic persist ──────────────────────────────────────────────
    try:
        final_status = SignalStatus.RISK_APPROVED if result.approved else SignalStatus.RISK_REJECTED
        signal_repo.update_status(db, signal, final_status)
        decision_repo.create_decision(db, signal.id, result)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("persist_decision_failed", extra={"signal_id": signal.id})
        masked = webhook_event_repo.mask_payload(raw_payload)
        webhook_event_repo.create_event(
            db,
            WebhookEventType.INTERNAL_ERROR,
            RejectionReason.INTERNAL_ERROR,
            masked,
            client_signal_id=parsed.client_signal_id,
            reason_detail="persist_decision_failed",
        )
        return _error_response(received_at), 500

    log.info(
        "pipeline_stage",
        extra={
            "stage": "risk_decision",
            "result": "approved" if result.approved else "rejected",
            "signal_id": signal.id,
            "client_signal_id": signal.client_signal_id,
            "ticker": signal.ticker,
            "reason_code": result.reason_code.value if result.reason_code else None,
            "is_enforcement_deferred": result.is_enforcement_deferred,
        },
    )

    http_status = 202 if result.approved else 200
    return _approved_response(signal, result, received_at), http_status


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_unsupported_asset(ticker: str, settings: Settings) -> bool:
    """Return True if ticker is crypto (contains /) or not in the configured allowlist."""
    if "/" in ticker:
        return True
    if settings.ALLOWED_TICKERS and ticker.upper() not in settings.ALLOWED_TICKERS:
        return True
    return False


def _map_to_signal_dict(parsed: WebhookSignalRequest) -> dict:
    return {
        "client_signal_id": parsed.client_signal_id,
        "strategy": parsed.strategy,
        "version": parsed.version,
        "ticker": parsed.ticker,
        "side": parsed.side.value,
        "price": str(parsed.price),
        "timeframe": parsed.timeframe,
        "bar_time_utc": parsed.bar_time,
        "event_time_utc": parsed.event_time,
        "exchange": parsed.exchange,
        "order_id": parsed.order_id,
        "stop_loss": str(parsed.stop_loss) if parsed.stop_loss is not None else None,
        "take_profit": str(parsed.take_profit) if parsed.take_profit is not None else None,
        "risk_hint": str(parsed.risk_hint) if parsed.risk_hint is not None else None,
        "position_size": str(parsed.position_size) if parsed.position_size is not None else None,
        "status": SignalStatus.RECEIVED.value,
    }


def _rejection_response(
    signal_id: Optional[str],
    client_signal_id: Optional[str],
    reason_code: RejectionReason,
    received_at: datetime,
    reason_detail: Optional[str] = None,
) -> WebhookResponse:
    return WebhookResponse(
        signal_id=signal_id,
        client_signal_id=client_signal_id,
        status=reason_code.value,
        approved=False,
        reason_code=reason_code.value,
        reason_detail=reason_detail,
        received_at=received_at,
    )


def _approved_response(signal: object, result: RiskDecisionResult, received_at: datetime) -> WebhookResponse:
    return WebhookResponse(
        signal_id=signal.id,
        client_signal_id=signal.client_signal_id,
        status=SignalStatus.RISK_APPROVED.value if result.approved else SignalStatus.RISK_REJECTED.value,
        approved=result.approved,
        reason_code=result.reason_code.value if result.reason_code else None,
        reason_detail=result.reason_detail,
        received_at=received_at,
    )


def _error_response(received_at: datetime) -> WebhookResponse:
    return WebhookResponse(
        status="internal_error",
        approved=False,
        reason_code="internal_error",
        reason_detail="An unexpected error occurred. Check server logs.",
        received_at=received_at,
    )
