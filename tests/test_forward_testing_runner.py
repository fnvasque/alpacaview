"""
Unit tests for src.forward_testing.runner.run_ticker().

No network, no DB. All external calls are mocked.
"""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import requests as requests_lib

from src.forward_testing.runner import RunResult, RunStatus, run_ticker
from src.signal_generator.data_fetcher import DataFetchError
from src.signal_generator.indicators import IndicatorResult

_UTC = timezone.utc
_BAR_TIME = datetime(2026, 5, 20, 14, 30, 0, tzinfo=_UTC)

_PATCHES = [
    "src.forward_testing.runner.fetch_ohlcv",
    "src.forward_testing.runner.compute_indicators",
    "src.forward_testing.runner.build_payload",
    "src.forward_testing.runner.requests.post",
]


def make_settings(**overrides) -> MagicMock:
    s = MagicMock()
    s.FORWARD_TESTING_SECRET = "test-secret"
    s.FORWARD_TESTING_BACKEND_URL = "http://127.0.0.1:8000"
    s.ATR_MULTIPLIER = Decimal("1.5")
    s.RISK_REWARD = Decimal("2.0")
    s.EMA_LENGTH = 21
    s.ATR_LENGTH = 14
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def make_indicator_result(crossover: bool = True) -> IndicatorResult:
    return IndicatorResult(
        ticker="SPY",
        timeframe="15m",
        current_close=Decimal("450.0000"),
        current_ema=Decimal("448.0000"),
        current_atr=Decimal("2.0000"),
        previous_close=Decimal("447.0000"),
        previous_ema=Decimal("448.5000"),
        bar_time=_BAR_TIME,
        crossover_detected=crossover,
    )


def make_mock_payload() -> dict:
    return {
        "secret": "test-secret",
        "strategy": "python_atr_generator",
        "version": "0.2b.0",
        "ticker": "SPY",
        "side": "buy",
        "price": "450.0000",
        "stop_loss": "447.0000",
        "take_profit": "456.0000",
        "timeframe": "15m",
        "bar_time": "2026-05-20T14:30:00Z",
        "event_time": "2026-05-20T14:31:00Z",
        "client_signal_id": "python_atr_generator:0.2b.0:SPY:15m:2026-05-20T14:30:00Z:buy",
    }


_MOCK_DF = MagicMock()


# ── Fetch error paths ──────────────────────────────────────────────────────────

def test_fetch_error_returns_error_status() -> None:
    with patch("src.forward_testing.runner.fetch_ohlcv", side_effect=DataFetchError("no data")):
        result = run_ticker("SPY", "15m", "5d", make_settings(), send=False, dry_run=True)
    assert result.status == RunStatus.ERROR
    assert result.error_message is not None


def test_unexpected_exception_returns_error_status() -> None:
    with patch("src.forward_testing.runner.fetch_ohlcv", side_effect=RuntimeError("boom")):
        result = run_ticker("SPY", "15m", "5d", make_settings(), send=False, dry_run=True)
    assert result.status == RunStatus.ERROR
    assert "unexpected" in result.error_message


# ── Indicator paths ────────────────────────────────────────────────────────────

def test_insufficient_data_returns_insufficient_data() -> None:
    with patch("src.forward_testing.runner.fetch_ohlcv", return_value=_MOCK_DF), \
         patch("src.forward_testing.runner.compute_indicators", return_value=None):
        result = run_ticker("SPY", "15m", "5d", make_settings(), send=False, dry_run=True)
    assert result.status == RunStatus.INSUFFICIENT_DATA


def test_no_crossover_returns_no_signal() -> None:
    ind = make_indicator_result(crossover=False)
    with patch("src.forward_testing.runner.fetch_ohlcv", return_value=_MOCK_DF), \
         patch("src.forward_testing.runner.compute_indicators", return_value=ind):
        result = run_ticker("SPY", "15m", "5d", make_settings(), send=False, dry_run=True)
    assert result.status == RunStatus.NO_SIGNAL
    assert result.bar_time == _BAR_TIME


def test_build_payload_none_returns_no_signal() -> None:
    ind = make_indicator_result(crossover=True)
    with patch("src.forward_testing.runner.fetch_ohlcv", return_value=_MOCK_DF), \
         patch("src.forward_testing.runner.compute_indicators", return_value=ind), \
         patch("src.forward_testing.runner.build_payload", return_value=None):
        result = run_ticker("SPY", "15m", "5d", make_settings(), send=False, dry_run=True)
    assert result.status == RunStatus.NO_SIGNAL


# ── Dry-run path ───────────────────────────────────────────────────────────────

def test_dry_run_with_signal_returns_signal_candidate() -> None:
    ind = make_indicator_result(crossover=True)
    payload = make_mock_payload()
    with patch("src.forward_testing.runner.fetch_ohlcv", return_value=_MOCK_DF), \
         patch("src.forward_testing.runner.compute_indicators", return_value=ind), \
         patch("src.forward_testing.runner.build_payload", return_value=payload):
        result = run_ticker("SPY", "15m", "5d", make_settings(), send=False, dry_run=True)
    assert result.status == RunStatus.SIGNAL_CANDIDATE
    assert result.client_signal_id == payload["client_signal_id"]


# ── Send paths ────────────────────────────────────────────────────────────────

def test_send_202_returns_risk_approved() -> None:
    ind = make_indicator_result(crossover=True)
    payload = make_mock_payload()
    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.json.return_value = {"signal_id": "abc", "approved": True, "reason_code": None, "reason_detail": None}
    with patch("src.forward_testing.runner.fetch_ohlcv", return_value=_MOCK_DF), \
         patch("src.forward_testing.runner.compute_indicators", return_value=ind), \
         patch("src.forward_testing.runner.build_payload", return_value=payload), \
         patch("src.forward_testing.runner.requests.post", return_value=mock_resp):
        result = run_ticker("SPY", "15m", "5d", make_settings(), send=True, dry_run=False)
    assert result.status == RunStatus.RISK_APPROVED
    assert result.backend_approved is True
    assert result.backend_status_code == 202


def test_send_200_returns_risk_rejected() -> None:
    ind = make_indicator_result(crossover=True)
    payload = make_mock_payload()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"signal_id": "abc", "approved": False, "reason_code": "max_daily_loss", "reason_detail": None}
    with patch("src.forward_testing.runner.fetch_ohlcv", return_value=_MOCK_DF), \
         patch("src.forward_testing.runner.compute_indicators", return_value=ind), \
         patch("src.forward_testing.runner.build_payload", return_value=payload), \
         patch("src.forward_testing.runner.requests.post", return_value=mock_resp):
        result = run_ticker("SPY", "15m", "5d", make_settings(), send=True, dry_run=False)
    assert result.status == RunStatus.RISK_REJECTED
    assert result.backend_approved is False
    assert result.backend_reason_code == "max_daily_loss"


def test_send_409_duplicate_returns_duplicate_signal() -> None:
    ind = make_indicator_result(crossover=True)
    payload = make_mock_payload()
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    mock_resp.json.return_value = {"reason_code": "duplicate_signal"}
    with patch("src.forward_testing.runner.fetch_ohlcv", return_value=_MOCK_DF), \
         patch("src.forward_testing.runner.compute_indicators", return_value=ind), \
         patch("src.forward_testing.runner.build_payload", return_value=payload), \
         patch("src.forward_testing.runner.requests.post", return_value=mock_resp):
        result = run_ticker("SPY", "15m", "5d", make_settings(), send=True, dry_run=False)
    assert result.status == RunStatus.DUPLICATE_SIGNAL
    assert result.backend_status_code == 409


def test_send_network_error_returns_error() -> None:
    ind = make_indicator_result(crossover=True)
    payload = make_mock_payload()
    with patch("src.forward_testing.runner.fetch_ohlcv", return_value=_MOCK_DF), \
         patch("src.forward_testing.runner.compute_indicators", return_value=ind), \
         patch("src.forward_testing.runner.build_payload", return_value=payload), \
         patch("src.forward_testing.runner.requests.post", side_effect=requests_lib.RequestException("timeout")):
        result = run_ticker("SPY", "15m", "5d", make_settings(), send=True, dry_run=False)
    assert result.status == RunStatus.ERROR
    assert result.error_message is not None


def test_send_unexpected_status_returns_signal_sent() -> None:
    ind = make_indicator_result(crossover=True)
    payload = make_mock_payload()
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_resp.json.return_value = {}
    with patch("src.forward_testing.runner.fetch_ohlcv", return_value=_MOCK_DF), \
         patch("src.forward_testing.runner.compute_indicators", return_value=ind), \
         patch("src.forward_testing.runner.build_payload", return_value=payload), \
         patch("src.forward_testing.runner.requests.post", return_value=mock_resp):
        result = run_ticker("SPY", "15m", "5d", make_settings(), send=True, dry_run=False)
    assert result.status == RunStatus.SIGNAL_SENT
    assert result.backend_status_code == 503


# ── Signal field correctness ───────────────────────────────────────────────────

def test_risk_reward_computed_correctly() -> None:
    ind = make_indicator_result(crossover=True)
    payload = {
        **make_mock_payload(),
        "price": "450.0000",
        "stop_loss": "447.0000",
        "take_profit": "456.0000",
    }
    with patch("src.forward_testing.runner.fetch_ohlcv", return_value=_MOCK_DF), \
         patch("src.forward_testing.runner.compute_indicators", return_value=ind), \
         patch("src.forward_testing.runner.build_payload", return_value=payload):
        result = run_ticker("SPY", "15m", "5d", make_settings(), send=False, dry_run=True)
    assert result.risk_reward == "2.0000"


def test_signal_fields_populated_on_send() -> None:
    ind = make_indicator_result(crossover=True)
    payload = make_mock_payload()
    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.json.return_value = {"signal_id": "xyz", "approved": True}
    with patch("src.forward_testing.runner.fetch_ohlcv", return_value=_MOCK_DF), \
         patch("src.forward_testing.runner.compute_indicators", return_value=ind), \
         patch("src.forward_testing.runner.build_payload", return_value=payload), \
         patch("src.forward_testing.runner.requests.post", return_value=mock_resp):
        result = run_ticker("SPY", "15m", "5d", make_settings(), send=True, dry_run=False)
    assert result.price == payload["price"]
    assert result.stop_loss == payload["stop_loss"]
    assert result.take_profit == payload["take_profit"]
    assert result.client_signal_id == payload["client_signal_id"]


# ── Security ──────────────────────────────────────────────────────────────────

def test_error_message_does_not_contain_secret() -> None:
    settings = make_settings(FORWARD_TESTING_SECRET="super-secret-value")
    with patch("src.forward_testing.runner.fetch_ohlcv", side_effect=DataFetchError("fetch error")):
        result = run_ticker("SPY", "15m", "5d", settings, send=False, dry_run=True)
    assert result.error_message is not None
    assert "super-secret-value" not in result.error_message
