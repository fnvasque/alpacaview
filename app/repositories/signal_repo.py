from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.signal import Signal
from app.schemas.enums import SignalStatus


def get_by_client_signal_id(db: Session, client_signal_id: str) -> Optional[Signal]:
    return db.query(Signal).filter(Signal.client_signal_id == client_signal_id).first()


def create(db: Session, signal_data: dict) -> Signal:
    """
    Insert a new Signal row. Calls db.flush() to populate the id.
    Caller owns the transaction (commit/rollback).
    """
    signal = Signal(**signal_data)
    db.add(signal)
    db.flush()
    db.refresh(signal)
    return signal


def update_status(db: Session, signal: Signal, status: SignalStatus) -> None:
    """Update signal status. No flush or commit — caller owns transaction."""
    signal.status = status.value


def get_approved_since(db: Session, since_utc: datetime) -> list[Signal]:
    """Return RISK_APPROVED signals created at or after since_utc."""
    return (
        db.query(Signal)
        .filter(
            Signal.status == SignalStatus.RISK_APPROVED.value,
            Signal.created_at_utc >= since_utc,
        )
        .all()
    )
