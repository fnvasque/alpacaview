"""
Unit tests for ResendClient.

Verifies HTTP contract: correct endpoint URL, Authorization header,
error mapping, and structured logging — without touching the network.
"""
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.integrations.resend_client import ResendClient, ResendClientError, ResendEmailContent

EMAIL_ID = "test-email-abc123"
API_KEY = "test-api-key"


def _make_mock_http_client(response: MagicMock) -> MagicMock:
    mock = MagicMock()
    mock.get = AsyncMock(return_value=response)
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


def _ok_response(email_id: str) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"id": email_id, "text": "hello", "html": None}
    return resp


# ── URL contract ───────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_fetch_email_calls_receiving_endpoint() -> None:
    mock_http = _make_mock_http_client(_ok_response(EMAIL_ID))

    with patch("app.integrations.resend_client.httpx.AsyncClient", return_value=mock_http):
        result = await ResendClient(api_key=API_KEY).fetch_email(EMAIL_ID)

    mock_http.get.assert_called_once_with(
        f"https://api.resend.com/emails/receiving/{EMAIL_ID}",
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    assert isinstance(result, ResendEmailContent)
    assert result.id == EMAIL_ID


# ── Auth header does not leak into logs ───────────────────────────────────────

@pytest.mark.anyio
async def test_fetch_email_does_not_log_api_key(caplog: pytest.LogCaptureFixture) -> None:
    mock_http = _make_mock_http_client(_ok_response(EMAIL_ID))

    with caplog.at_level(logging.DEBUG, logger="app.integrations.resend_client"):
        with patch("app.integrations.resend_client.httpx.AsyncClient", return_value=mock_http):
            await ResendClient(api_key=API_KEY).fetch_email(EMAIL_ID)

    for record in caplog.records:
        assert API_KEY not in record.getMessage()
        assert API_KEY not in str(record.__dict__)


# ── HTTP error logging ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_fetch_email_404_logs_email_id_and_status(caplog: pytest.LogCaptureFixture) -> None:
    error_response = MagicMock()
    error_response.status_code = 404
    error_response.request = MagicMock()

    http_error = httpx.HTTPStatusError("404", request=error_response.request, response=error_response)
    resp = MagicMock()
    resp.raise_for_status = MagicMock(side_effect=http_error)
    mock_http = _make_mock_http_client(resp)

    with caplog.at_level(logging.WARNING, logger="app.integrations.resend_client"):
        with patch("app.integrations.resend_client.httpx.AsyncClient", return_value=mock_http):
            with pytest.raises(ResendClientError):
                await ResendClient(api_key=API_KEY).fetch_email(EMAIL_ID)

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert record.__dict__["email_id"] == EMAIL_ID
    assert record.__dict__["status_code"] == 404
    assert API_KEY not in record.getMessage()
    assert API_KEY not in str(record.__dict__)


@pytest.mark.anyio
async def test_fetch_email_http_error_raises_resend_client_error() -> None:
    error_response = MagicMock()
    error_response.status_code = 503
    error_response.request = MagicMock()

    http_error = httpx.HTTPStatusError("503", request=error_response.request, response=error_response)
    resp = MagicMock()
    resp.raise_for_status = MagicMock(side_effect=http_error)
    mock_http = _make_mock_http_client(resp)

    with patch("app.integrations.resend_client.httpx.AsyncClient", return_value=mock_http):
        with pytest.raises(ResendClientError):
            await ResendClient(api_key=API_KEY).fetch_email(EMAIL_ID)


@pytest.mark.anyio
async def test_fetch_email_request_error_raises_resend_client_error() -> None:
    resp = MagicMock()
    resp.raise_for_status = MagicMock(side_effect=httpx.ConnectError("timeout"))
    mock_http = _make_mock_http_client(resp)

    with patch("app.integrations.resend_client.httpx.AsyncClient", return_value=mock_http):
        with pytest.raises(ResendClientError):
            await ResendClient(api_key=API_KEY).fetch_email(EMAIL_ID)


# ── Response parsing ───────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_fetch_email_ignores_extra_fields() -> None:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "id": EMAIL_ID,
        "text": "plain body",
        "html": "<p>html body</p>",
        "subject": "TradingView Alert",
        "from": "alerts@tradingview.com",
    }
    mock_http = _make_mock_http_client(resp)

    with patch("app.integrations.resend_client.httpx.AsyncClient", return_value=mock_http):
        result = await ResendClient(api_key=API_KEY).fetch_email(EMAIL_ID)

    assert result.id == EMAIL_ID
    assert result.text == "plain body"
    assert result.html == "<p>html body</p>"
