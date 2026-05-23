"""
Integration tests for POST /integrations/resend/inbound.

Uses TestClient with in-memory SQLite. All response matrix conditions and
pipeline passthrough scenarios have a dedicated test per the REASONS Canvas.
"""
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.integrations.resend_client import ResendClient, ResendClientError, ResendEmailContent, get_resend_client
from app.main import create_app
from app.models.signal import Signal

ENDPOINT = "/integrations/resend/inbound"


# ── Helpers ────────────────────────────────────────────────────────────────────

def resend_event_payload(email_id: str) -> dict:
    return {"type": "email.received", "data": {"id": email_id}}


def email_content_with_json(raw_signal_dict: dict, email_id: str) -> ResendEmailContent:
    return ResendEmailContent(id=email_id, text=json.dumps(raw_signal_dict))


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_resend_client() -> MagicMock:
    client = MagicMock(spec=ResendClient)
    client.fetch_email = AsyncMock()
    return client


@pytest.fixture
def resend_settings() -> Settings:
    return Settings(
        WEBHOOK_SECRET="test-secret",
        DATABASE_URL="sqlite://",
        INITIAL_EQUITY=Decimal("10000"),
        STOP_AFTER_DAILY_TARGET=False,
        KILL_SWITCH=False,
        ALLOWED_TICKERS=["SPY", "QQQ", "AAPL", "MSFT", "NVDA"],
        MAX_DAILY_TRADES=3,
        MAX_DAILY_LOSS_PCT=Decimal("0.0075"),
        MAX_WEEKLY_LOSS_PCT=Decimal("0.025"),
        MAX_CONSECUTIVE_LOSSES=2,
        DAILY_TARGET_PCT=Decimal("0.003"),
        MIN_RISK_REWARD=Decimal("1.5"),
        ALLOWED_TIMEFRAMES=["5m", "15m", "1h"],
        MAX_SIGNAL_AGE_SECONDS=900,
        RESEND_RECEIVING_ENABLED=True,
        RESEND_API_KEY="test-resend-key",
        RESEND_MAX_EMAIL_BODY_CHARS=50000,
    )


@pytest.fixture
def resend_test_client(
    db: Session,
    resend_settings: Settings,
    mock_resend_client: MagicMock,
) -> TestClient:
    application = create_app()

    def override_get_db():
        yield db

    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_settings] = lambda: resend_settings
    application.dependency_overrides[get_resend_client] = lambda: mock_resend_client

    with TestClient(application) as test_client:
        yield test_client

    application.dependency_overrides.clear()


# ── RESEND_RECEIVING_ENABLED=False (default) ───────────────────────────────────

def test_disabled_returns_404(client: TestClient) -> None:
    resp = client.post(ENDPOINT, json=resend_event_payload("email-1"))
    assert resp.status_code == 404


# ── RESEND_API_KEY missing ─────────────────────────────────────────────────────

def test_missing_api_key_returns_503(db: Session) -> None:
    no_key_settings = Settings(
        WEBHOOK_SECRET="test-secret",
        DATABASE_URL="sqlite://",
        INITIAL_EQUITY=Decimal("10000"),
        STOP_AFTER_DAILY_TARGET=False,
        KILL_SWITCH=False,
        ALLOWED_TICKERS=["SPY"],
        MAX_DAILY_TRADES=3,
        MAX_DAILY_LOSS_PCT=Decimal("0.0075"),
        MAX_WEEKLY_LOSS_PCT=Decimal("0.025"),
        MAX_CONSECUTIVE_LOSSES=2,
        DAILY_TARGET_PCT=Decimal("0.003"),
        RESEND_RECEIVING_ENABLED=True,
        RESEND_API_KEY=None,
    )
    application = create_app()

    def override_get_db():
        yield db

    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_settings] = lambda: no_key_settings

    with TestClient(application) as c:
        resp = c.post(ENDPOINT, json=resend_event_payload("email-1"))

    application.dependency_overrides.clear()

    assert resp.status_code == 503
    assert resp.json()["reason_code"] == "resend_not_configured"


# ── Event type ignored ─────────────────────────────────────────────────────────

def test_non_email_received_event_returns_200(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
    db: Session,
) -> None:
    payload = {"type": "email.delivered", "data": {"id": "email-1"}}
    resp = resend_test_client.post(ENDPOINT, json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ignored"
    assert body["reason_code"] == "unsupported_resend_event_type"
    mock_resend_client.fetch_email.assert_not_called()
    assert db.query(Signal).count() == 0


def test_non_email_received_event_returns_200_ignored(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
    db: Session,
) -> None:
    # Payload with no recognizable type field — must be ignored, never reach fetch or pipeline
    resp = resend_test_client.post(ENDPOINT, json={"wrong_field": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ignored"
    assert body["reason_code"] == "unsupported_resend_event_type"
    mock_resend_client.fetch_email.assert_not_called()
    assert db.query(Signal).count() == 0


# ── Resend API failure ─────────────────────────────────────────────────────────

def test_resend_api_failure_returns_502(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
) -> None:
    mock_resend_client.fetch_email.side_effect = ResendClientError("upstream error")
    resp = resend_test_client.post(ENDPOINT, json=resend_event_payload("email-fail"))
    assert resp.status_code == 502


# ── Body too large ─────────────────────────────────────────────────────────────

def test_body_too_large_returns_413(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
    db: Session,
) -> None:
    mock_resend_client.fetch_email.return_value = ResendEmailContent(
        id="email-big",
        text="x" * 50001,
        html=None,
    )
    resp = resend_test_client.post(ENDPOINT, json=resend_event_payload("email-big"))
    assert resp.status_code == 413
    assert resp.json()["reason_code"] == "email_body_too_large"
    mock_resend_client.fetch_email.assert_called_once()
    assert db.query(Signal).count() == 0


# ── No JSON in email ───────────────────────────────────────────────────────────

def test_plain_text_no_json_returns_422(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
) -> None:
    mock_resend_client.fetch_email.return_value = ResendEmailContent(
        id="email-x", text="No JSON here", html=None
    )
    resp = resend_test_client.post(ENDPOINT, json=resend_event_payload("email-x"))
    assert resp.status_code == 422


def test_html_no_json_after_strip_returns_422(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
) -> None:
    mock_resend_client.fetch_email.return_value = ResendEmailContent(
        id="email-x", text=None, html="<p>Nothing here</p>"
    )
    resp = resend_test_client.post(ENDPOINT, json=resend_event_payload("email-x"))
    assert resp.status_code == 422


def test_empty_body_returns_422(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
) -> None:
    mock_resend_client.fetch_email.return_value = ResendEmailContent(
        id="email-x", text=None, html=None
    )
    resp = resend_test_client.post(ENDPOINT, json=resend_event_payload("email-x"))
    assert resp.status_code == 422


def test_malformed_json_block_returns_422(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
) -> None:
    mock_resend_client.fetch_email.return_value = ResendEmailContent(
        id="email-x", text="{not: valid json}", html=None
    )
    resp = resend_test_client.post(ENDPOINT, json=resend_event_payload("email-x"))
    assert resp.status_code == 422


# ── Happy path — plain text JSON ───────────────────────────────────────────────

def test_valid_signal_in_plain_text_returns_202(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
    valid_payload: dict,
) -> None:
    email_id = str(uuid4())
    mock_resend_client.fetch_email.return_value = email_content_with_json(valid_payload, email_id)
    resp = resend_test_client.post(ENDPOINT, json=resend_event_payload(email_id))
    assert resp.status_code == 202
    assert resp.json()["approved"] is True


# ── Happy path — HTML fallback ─────────────────────────────────────────────────

def test_valid_signal_in_html_returns_202(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
    valid_payload: dict,
) -> None:
    email_id = str(uuid4())
    mock_resend_client.fetch_email.return_value = ResendEmailContent(
        id=email_id,
        text=None,
        html=f"<p>TradingView Alert</p><pre>{json.dumps(valid_payload)}</pre>",
    )
    resp = resend_test_client.post(ENDPOINT, json=resend_event_payload(email_id))
    assert resp.status_code == 202
    assert resp.json()["approved"] is True


# ── JSON extraction — first block wins ────────────────────────────────────────

def test_first_json_block_extracted(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
    valid_payload: dict,
) -> None:
    email_id = str(uuid4())
    mock_resend_client.fetch_email.return_value = ResendEmailContent(
        id=email_id,
        text=f"{json.dumps(valid_payload)} some trailing text {{invalid",
        html=None,
    )
    resp = resend_test_client.post(ENDPOINT, json=resend_event_payload(email_id))
    assert resp.status_code == 202
    assert resp.json()["approved"] is True


# ── Pipeline delegation — bad secret ──────────────────────────────────────────

def test_bad_secret_in_extracted_json_returns_401(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
    valid_payload: dict,
) -> None:
    email_id = str(uuid4())
    bad_payload = {**valid_payload, "secret": "wrong-secret"}
    mock_resend_client.fetch_email.return_value = email_content_with_json(bad_payload, email_id)
    resp = resend_test_client.post(ENDPOINT, json=resend_event_payload(email_id))
    assert resp.status_code == 401


# ── Pipeline delegation — duplicate signal ────────────────────────────────────

def test_resend_duplicate_signal_returns_200_to_resend(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
    valid_payload: dict,
    db: Session,
) -> None:
    # First request — accepted
    first_email_id = str(uuid4())
    mock_resend_client.fetch_email.return_value = email_content_with_json(valid_payload, first_email_id)
    first = resend_test_client.post(ENDPOINT, json=resend_event_payload(first_email_id))
    assert first.status_code == 202

    # Second request — same signal payload (duplicate client_signal_id), different email
    second_email_id = str(uuid4())
    mock_resend_client.fetch_email.return_value = email_content_with_json(valid_payload, second_email_id)
    second = resend_test_client.post(ENDPOINT, json=resend_event_payload(second_email_id))

    # Resend must receive 200 so it does not retry the email
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "duplicate_signal"
    assert body["reason_code"] == "duplicate_signal"

    # Pipeline must not have created a second Signal
    from app.models.signal import Signal
    assert db.query(Signal).count() == 1


# ── Invalid JSON body at router ────────────────────────────────────────────────

def test_invalid_json_body_returns_400(resend_test_client: TestClient) -> None:
    resp = resend_test_client.post(
        ENDPOINT,
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400


# ── email.received with missing email_id ──────────────────────────────────────

def test_email_received_missing_email_id_returns_422(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
) -> None:
    # type is email.received but data contains neither id nor email_id
    resp = resend_test_client.post(
        ENDPOINT, json={"type": "email.received", "data": {}}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_resend_event"
    mock_resend_client.fetch_email.assert_not_called()


def test_email_received_missing_data_field_returns_422(
    resend_test_client: TestClient,
    mock_resend_client: MagicMock,
) -> None:
    # type is email.received but data key is absent entirely
    resp = resend_test_client.post(
        ENDPOINT, json={"type": "email.received"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_resend_event"
    mock_resend_client.fetch_email.assert_not_called()
