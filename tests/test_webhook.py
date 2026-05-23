"""
Integration tests for POST /webhook/signal.

Uses TestClient with in-memory SQLite. All risk rules and pipeline stages
have at least one test per the REASONS Canvas acceptance criteria.
"""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.decision import RiskDecision
from app.models.signal import Signal
from app.models.webhook_event import WebhookEvent
from app.repositories import kill_switch_repo, signal_repo
from app.schemas.enums import SignalStatus


ENDPOINT = "/webhook/signal"


# ── Happy path ─────────────────────────────────────────────────────────────────

def test_valid_buy_signal_returns_202(client, valid_payload):
    resp = client.post(ENDPOINT, json=valid_payload)
    assert resp.status_code == 202
    body = resp.json()
    assert body["approved"] is True


def test_signal_persisted_in_signals_table(client, db, valid_payload):
    client.post(ENDPOINT, json=valid_payload)
    signals = db.query(Signal).all()
    assert len(signals) == 1
    assert signals[0].status == SignalStatus.RISK_APPROVED.value


def test_risk_decision_persisted_approved(client, db, valid_payload):
    client.post(ENDPOINT, json=valid_payload)
    decisions = db.query(RiskDecision).all()
    assert len(decisions) == 1
    assert decisions[0].approved is True


def test_no_webhook_event_on_success(client, db, valid_payload):
    client.post(ENDPOINT, json=valid_payload)
    events = db.query(WebhookEvent).all()
    assert len(events) == 0


# ── Invalid JSON ───────────────────────────────────────────────────────────────

def test_invalid_json_returns_400(client):
    resp = client.post(
        ENDPOINT,
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_invalid_json_creates_webhook_event(client, db):
    client.post(
        ENDPOINT,
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    events = db.query(WebhookEvent).all()
    assert len(events) == 1
    assert events[0].event_type == "schema_invalid"

    signals = db.query(Signal).all()
    assert len(signals) == 0


# ── Auth failures ──────────────────────────────────────────────────────────────

def test_invalid_secret_returns_401(client, make_payload):
    resp = client.post(ENDPOINT, json=make_payload(secret="wrong-secret"))
    assert resp.status_code == 401
    body = resp.json()
    assert body["reason_code"] == "invalid_secret"


def test_invalid_secret_creates_webhook_event(client, db, make_payload):
    client.post(ENDPOINT, json=make_payload(secret="wrong-secret"))
    events = db.query(WebhookEvent).all()
    assert len(events) == 1
    assert events[0].event_type == "auth_failed"


def test_invalid_secret_no_signal_created(client, db, make_payload):
    client.post(ENDPOINT, json=make_payload(secret="wrong-secret"))
    assert db.query(Signal).count() == 0


def test_secret_masked_in_webhook_event(client, db, make_payload):
    client.post(ENDPOINT, json=make_payload(secret="super-secret-value"))
    event = db.query(WebhookEvent).first()
    assert event is not None
    assert "super-secret-value" not in event.raw_payload_masked
    assert "***" in event.raw_payload_masked


# ── Schema failures ────────────────────────────────────────────────────────────

def test_missing_ticker_returns_422(client, make_payload):
    payload = make_payload()
    del payload["ticker"]
    resp = client.post(ENDPOINT, json=payload)
    assert resp.status_code == 422


def test_schema_failure_creates_webhook_event_not_signal(client, db, make_payload):
    payload = make_payload()
    del payload["ticker"]
    client.post(ENDPOINT, json=payload)

    events = db.query(WebhookEvent).all()
    assert len(events) == 1
    assert events[0].event_type == "schema_invalid"

    assert db.query(Signal).count() == 0


# ── Side validation ────────────────────────────────────────────────────────────

def test_sell_returns_422_unsupported_side(client, make_payload):
    resp = client.post(ENDPOINT, json=make_payload(side="sell"))
    assert resp.status_code == 422
    body = resp.json()
    assert body["reason_code"] == "unsupported_side"


def test_sell_creates_webhook_event_not_signal(client, db, make_payload):
    client.post(ENDPOINT, json=make_payload(side="sell"))

    events = db.query(WebhookEvent).all()
    assert len(events) == 1
    assert events[0].event_type == "unsupported_side"

    assert db.query(Signal).count() == 0


# ── Asset class ────────────────────────────────────────────────────────────────

def test_crypto_slash_ticker_rejected(client, make_payload):
    resp = client.post(ENDPOINT, json=make_payload(ticker="BTC/USD"))
    assert resp.status_code == 422
    body = resp.json()
    assert body["reason_code"] == "unsupported_asset_class"


def test_ticker_not_in_allowlist_rejected(client, make_payload):
    resp = client.post(ENDPOINT, json=make_payload(ticker="TSLA"))
    assert resp.status_code == 422
    body = resp.json()
    assert body["reason_code"] == "unsupported_asset_class"


def test_asset_rejection_creates_webhook_event_not_signal(client, db, make_payload):
    client.post(ENDPOINT, json=make_payload(ticker="BTC/USD"))

    events = db.query(WebhookEvent).all()
    assert len(events) == 1
    assert events[0].event_type == "unsupported_asset_class"

    assert db.query(Signal).count() == 0


# ── Idempotency ────────────────────────────────────────────────────────────────

def test_duplicate_returns_409(client, valid_payload):
    client.post(ENDPOINT, json=valid_payload)
    resp = client.post(ENDPOINT, json=valid_payload)
    assert resp.status_code == 409


def test_duplicate_creates_webhook_event(client, db, valid_payload):
    client.post(ENDPOINT, json=valid_payload)
    client.post(ENDPOINT, json=valid_payload)

    events = db.query(WebhookEvent).all()
    assert len(events) == 1
    assert events[0].event_type == "duplicate_signal"


def test_no_second_signal_on_duplicate(client, db, valid_payload):
    client.post(ENDPOINT, json=valid_payload)
    client.post(ENDPOINT, json=valid_payload)
    assert db.query(Signal).count() == 1


def test_no_second_risk_decision_on_duplicate(client, db, valid_payload):
    client.post(ENDPOINT, json=valid_payload)
    client.post(ENDPOINT, json=valid_payload)
    assert db.query(RiskDecision).count() == 1


# ── Kill switch ────────────────────────────────────────────────────────────────

def test_kill_switch_rejects_with_200_risk_rejected(client, db, valid_payload):
    kill_switch_repo.set_active(db, active=True, reason="test")
    resp = client.post(ENDPOINT, json=valid_payload)

    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] is False
    assert body["reason_code"] == "kill_switch_active"


def test_kill_switch_signal_status_is_risk_rejected(client, db, valid_payload):
    kill_switch_repo.set_active(db, active=True, reason="test")
    client.post(ENDPOINT, json=valid_payload)

    signal = db.query(Signal).first()
    assert signal is not None
    assert signal.status == SignalStatus.RISK_REJECTED.value


# ── Max daily trades ───────────────────────────────────────────────────────────

def test_max_daily_trades_rejects_4th_signal(client, db, settings, make_payload):
    """Seed 3 risk_approved signals for today, then send a 4th — must be rejected."""
    now_utc = datetime.now(timezone.utc)
    for i in range(3):
        sig = Signal(
            client_signal_id=f"seed-signal-{i}",
            strategy="test",
            version="1.0",
            ticker="SPY",
            side="buy",
            price="450.00",
            timeframe="5m",
            bar_time_utc=now_utc,
            event_time_utc=now_utc,
            status=SignalStatus.RISK_APPROVED.value,
            created_at_utc=now_utc,
        )
        db.add(sig)
    db.commit()

    resp = client.post(ENDPOINT, json=make_payload(client_signal_id=str(uuid4())))
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] is False
    assert body["reason_code"] == "max_daily_trades_reached"


# ── Audit / security ──────────────────────────────────────────────────────────

def test_secret_not_in_response_body(client, settings, valid_payload):
    resp = client.post(ENDPOINT, json=valid_payload)
    assert settings.WEBHOOK_SECRET not in resp.text


def test_approved_true_message_no_execution_language(client, valid_payload):
    """Response must not contain 'execut' (execution, execute, executed, etc.)."""
    resp = client.post(ENDPOINT, json=valid_payload)
    assert "execut" not in resp.text.lower()
