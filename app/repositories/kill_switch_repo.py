from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.kill_switch import KillSwitchState


def get_state(db: Session) -> Optional[KillSwitchState]:
    """Return the singleton kill switch row (id=1), or None if it does not exist."""
    return db.query(KillSwitchState).filter(KillSwitchState.id == 1).first()


def set_active(db: Session, active: bool, reason: Optional[str] = None) -> KillSwitchState:
    """Upsert the singleton kill switch row (id=1)."""
    row = get_state(db)
    if row is None:
        row = KillSwitchState(id=1, active=active, reason=reason)
        if active:
            row.activated_at_utc = datetime.now(timezone.utc)
        db.add(row)
    else:
        row.active = active
        row.reason = reason
        if active:
            row.activated_at_utc = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row
