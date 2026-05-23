from sqlalchemy.orm import Session

from app.models.decision import RiskDecision
from app.schemas.risk import RiskDecisionResult


def create_decision(db: Session, signal_id: str, result: RiskDecisionResult) -> RiskDecision:
    """
    Map a RiskDecisionResult value object to a RiskDecision ORM row and insert it.
    No commit — caller owns the transaction.
    """
    decision = RiskDecision(
        signal_id=signal_id,
        approved=result.approved,
        reason_code=result.reason_code.value if result.reason_code else None,
        reason_detail=result.reason_detail,
        is_enforcement_deferred=result.is_enforcement_deferred,
    )
    db.add(decision)
    db.flush()
    return decision
