"""
Risk Engine — pure evaluation function.

PURITY GUARANTEE: This module must not import from app.models or sqlalchemy.
It receives all inputs as value objects (RiskSignalSnapshot, TradingContext, Settings)
and returns a RiskDecisionResult. No I/O, no side effects, no DB access.

approved=True means risk-approved for observability only. V0 does not execute orders.
"""
import logging
from typing import Optional

from app.config import Settings
from app.schemas.enums import RejectionReason
from app.schemas.risk import RiskDecisionResult, RiskSignalSnapshot, TradingContext

log = logging.getLogger(__name__)


def evaluate(
    snapshot: RiskSignalSnapshot,
    context: TradingContext,
    settings: Settings,
) -> RiskDecisionResult:
    """
    Evaluate a signal against all risk limits.

    Enforced in V0 (return approved=False immediately):
        1. Kill switch active
        2. Max daily trades reached

    Deferred in V0 (log warning, return approved=True with is_enforcement_deferred=True):
        3. Daily target would be reached  (STOP_AFTER_DAILY_TARGET has no effect in V0)
        4. Daily loss limit would be exceeded
        5. Weekly loss limit would be exceeded
        6. Consecutive losses threshold reached

    All deferred conditions are evaluated; the first triggered sets the reason_code.
    """
    log.debug(
        "risk_engine_evaluate",
        extra={
            "client_signal_id": snapshot.client_signal_id,
            "ticker": snapshot.ticker,
            "daily_trade_count": context.daily_trade_count,
            "kill_switch_active": context.kill_switch_active,
        },
    )

    # ── Enforced checks ────────────────────────────────────────────────────────

    if context.kill_switch_active:
        log.info(
            "risk_engine_decision",
            extra={
                "result": "rejected",
                "reason": RejectionReason.KILL_SWITCH_ACTIVE.value,
                "client_signal_id": snapshot.client_signal_id,
                "enforced": True,
            },
        )
        return RiskDecisionResult(
            approved=False,
            reason_code=RejectionReason.KILL_SWITCH_ACTIVE,
            is_enforcement_deferred=False,
        )

    if context.daily_trade_count >= settings.MAX_DAILY_TRADES:
        detail = f"daily_trade_count={context.daily_trade_count} max={settings.MAX_DAILY_TRADES}"
        log.info(
            "risk_engine_decision",
            extra={
                "result": "rejected",
                "reason": RejectionReason.MAX_DAILY_TRADES_REACHED.value,
                "client_signal_id": snapshot.client_signal_id,
                "detail": detail,
                "enforced": True,
            },
        )
        return RiskDecisionResult(
            approved=False,
            reason_code=RejectionReason.MAX_DAILY_TRADES_REACHED,
            reason_detail=detail,
            is_enforcement_deferred=False,
        )

    # ── Deferred checks (V0) ───────────────────────────────────────────────────
    # STOP_AFTER_DAILY_TARGET is reserved for V1/V2 and has no effect here.
    # All four deferred checks are evaluated; first triggered sets reason_code.

    deferred_reason: Optional[RejectionReason] = None
    deferred_detail: Optional[str] = None

    def _record_deferred(reason: RejectionReason, detail: str) -> None:
        nonlocal deferred_reason, deferred_detail
        log.warning(
            "deferred_limit_triggered",
            extra={
                "reason": reason.value,
                "detail": detail,
                "client_signal_id": snapshot.client_signal_id,
                "ticker": snapshot.ticker,
                "enforcement": "deferred_v1",
            },
        )
        if deferred_reason is None:
            deferred_reason = reason
            deferred_detail = detail

    if context.daily_target_would_be_reached:
        _record_deferred(
            RejectionReason.DAILY_TARGET_REACHED,
            "daily_target_pct_deferred_v0",
        )

    if context.daily_pnl_pct <= -abs(settings.MAX_DAILY_LOSS_PCT):
        _record_deferred(
            RejectionReason.DAILY_LOSS_LIMIT_EXCEEDED,
            f"daily_pnl_pct={context.daily_pnl_pct}",
        )

    if context.weekly_pnl_pct <= -abs(settings.MAX_WEEKLY_LOSS_PCT):
        _record_deferred(
            RejectionReason.WEEKLY_LOSS_LIMIT_EXCEEDED,
            f"weekly_pnl_pct={context.weekly_pnl_pct}",
        )

    if context.consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES:
        _record_deferred(
            RejectionReason.CONSECUTIVE_LOSSES_EXCEEDED,
            f"consecutive_losses={context.consecutive_losses}",
        )

    if deferred_reason is not None:
        log.info(
            "risk_engine_decision",
            extra={
                "result": "approved_deferred",
                "reason": deferred_reason.value,
                "client_signal_id": snapshot.client_signal_id,
                "enforcement": "deferred_v1",
            },
        )
        return RiskDecisionResult(
            approved=True,
            reason_code=deferred_reason,
            reason_detail=deferred_detail,
            is_enforcement_deferred=True,
        )

    # ── All clear ──────────────────────────────────────────────────────────────
    log.info(
        "risk_engine_decision",
        extra={
            "result": "approved",
            "client_signal_id": snapshot.client_signal_id,
            "ticker": snapshot.ticker,
        },
    )
    return RiskDecisionResult(approved=True)
