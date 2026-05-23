"""
Integration tests for signal quality validation via POST /webhook.

Uses TestClient with in-memory SQLite. Exercises the full pipeline path
for each quality reason code plus the happy path.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.webhook_event import WebhookEvent
from app.schemas.enums import WebhookEventType

ENDPOINT = "/webhook/signal"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _event_time_iso(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=offset_seconds)).isoformat()


def _bar_time_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()


# ── Happy path ─────────────────────────────────────────────────────────────────

def test_valid_buy_signal_with_quality_fields_returns_202(
    client: TestClient,
    valid_payload: dict,
) -> None:
    resp = client.post(ENDPOINT, json=valid_payload)
    assert resp.status_code == 202
    assert resp.json()["approved"] is True


# ── invalid_price ──────────────────────────────────────────────────────────────

def test_price_zero_returns_422_invalid_price(
    client: TestClient,
    make_payload,
    db: Session,
) -> None:
    payload = make_payload(price="0", stop_loss="445.00", take_profit="458.00")
    resp = client.post(ENDPOINT, json=payload)
    assert resp.status_code == 422
    assert resp.json()["reason_code"] == "invalid_price"
    event = db.query(WebhookEvent).one()
    assert event.event_type == WebhookEventType.SIGNAL_QUALITY_REJECTED.value
    assert event.reason_code == "invalid_price"


# ── invalid_stop_loss ──────────────────────────────────────────────────────────

def test_missing_stop_loss_returns_422_invalid_stop_loss(
    client: TestClient,
    make_payload,
    db: Session,
) -> None:
    payload = make_payload(take_profit="458.00")
    payload.pop("stop_loss", None)
    resp = client.post(ENDPOINT, json=payload)
    assert resp.status_code == 422
    assert resp.json()["reason_code"] == "invalid_stop_loss"
    event = db.query(WebhookEvent).one()
    assert event.event_type == WebhookEventType.SIGNAL_QUALITY_REJECTED.value


# ── invalid_take_profit ────────────────────────────────────────────────────────

def test_missing_take_profit_returns_422_invalid_take_profit(
    client: TestClient,
    make_payload,
    db: Session,
) -> None:
    payload = make_payload(stop_loss="445.00")
    payload.pop("take_profit", None)
    resp = client.post(ENDPOINT, json=payload)
    assert resp.status_code == 422
    assert resp.json()["reason_code"] == "invalid_take_profit"
    event = db.query(WebhookEvent).one()
    assert event.event_type == WebhookEventType.SIGNAL_QUALITY_REJECTED.value


# ── stop_loss_above_entry ──────────────────────────────────────────────────────

def test_stop_loss_above_price_returns_422(
    client: TestClient,
    make_payload,
) -> None:
    payload = make_payload(price="450.00", stop_loss="455.00", take_profit="465.00")
    resp = client.post(ENDPOINT, json=payload)
    assert resp.status_code == 422
    assert resp.json()["reason_code"] == "stop_loss_above_entry"


# ── take_profit_below_entry ────────────────────────────────────────────────────

def test_take_profit_below_price_returns_422(
    client: TestClient,
    make_payload,
) -> None:
    payload = make_payload(price="450.00", stop_loss="445.00", take_profit="440.00")
    resp = client.post(ENDPOINT, json=payload)
    assert resp.status_code == 422
    assert resp.json()["reason_code"] == "take_profit_below_entry"


# ── risk_reward_too_low ────────────────────────────────────────────────────────

def test_low_rr_returns_422_risk_reward_too_low(
    client: TestClient,
    make_payload,
) -> None:
    # rr = (464-450)/(450-440) = 14/10 = 1.4 < 1.5
    payload = make_payload(price="450.00", stop_loss="440.00", take_profit="464.00")
    resp = client.post(ENDPOINT, json=payload)
    assert resp.status_code == 422
    assert resp.json()["reason_code"] == "risk_reward_too_low"


# ── unsupported_timeframe ──────────────────────────────────────────────────────

def test_unsupported_timeframe_returns_422(
    client: TestClient,
    make_payload,
) -> None:
    payload = make_payload(timeframe="4h")
    resp = client.post(ENDPOINT, json=payload)
    assert resp.status_code == 422
    assert resp.json()["reason_code"] == "unsupported_timeframe"


# ── stale_signal ───────────────────────────────────────────────────────────────

def test_stale_signal_returns_422(
    client: TestClient,
    make_payload,
) -> None:
    payload = make_payload(event_time=_event_time_iso(offset_seconds=1000))
    resp = client.post(ENDPOINT, json=payload)
    assert resp.status_code == 422
    assert resp.json()["reason_code"] == "stale_signal"


# ── No Signal record on quality rejection ─────────────────────────────────────

def test_quality_rejection_does_not_persist_signal(
    client: TestClient,
    make_payload,
    db: Session,
) -> None:
    from app.models.signal import Signal

    payload = make_payload(price="0", stop_loss="445.00", take_profit="458.00")
    resp = client.post(ENDPOINT, json=payload)
    assert resp.status_code == 422
    assert db.query(Signal).count() == 0
    assert db.query(WebhookEvent).count() == 1
