"""
Unit tests for src.forward_testing.cli.

No real network, no real DB. All external calls are mocked.
Uses click.testing.CliRunner for invocation.
"""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest
from click.testing import CliRunner

from src.forward_testing.cli import main
from src.forward_testing.runner import RunResult, RunStatus

_UTC = timezone.utc
_BAR_TIME = datetime(2026, 5, 20, 14, 30, 0, tzinfo=_UTC)


def make_settings(**overrides) -> MagicMock:
    s = MagicMock()
    s.FORWARD_TESTING_ENABLED = True
    s.FORWARD_TESTING_TICKERS = ["SPY"]
    s.FORWARD_TESTING_TIMEFRAME = "15m"
    s.FORWARD_TESTING_PERIOD = "5d"
    s.FORWARD_TESTING_DB_URL = "sqlite://"
    s.FORWARD_TESTING_SECRET = "test-secret"
    s.FORWARD_TESTING_BACKEND_URL = "http://127.0.0.1:8000"
    s.ATR_MULTIPLIER = Decimal("1.5")
    s.RISK_REWARD = Decimal("2.0")
    s.EMA_LENGTH = 21
    s.ATR_LENGTH = 14
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def make_no_signal_result(ticker: str = "SPY") -> RunResult:
    return RunResult(ticker=ticker, timeframe="15m", period="5d", status=RunStatus.NO_SIGNAL)


def make_error_result(ticker: str = "SPY") -> RunResult:
    return RunResult(ticker=ticker, timeframe="15m", period="5d", status=RunStatus.ERROR, error_message="fetch failed")


def make_signal_sent_result(ticker: str = "SPY") -> RunResult:
    return RunResult(ticker=ticker, timeframe="15m", period="5d", status=RunStatus.SIGNAL_SENT,
                     backend_status_code=503, error_message="unexpected HTTP 503")


def make_risk_rejected_result(ticker: str = "SPY") -> RunResult:
    return RunResult(ticker=ticker, timeframe="15m", period="5d", status=RunStatus.RISK_REJECTED,
                     backend_status_code=200, backend_approved=False, backend_reason_code="max_daily_loss")


def make_duplicate_result(ticker: str = "SPY") -> RunResult:
    return RunResult(ticker=ticker, timeframe="15m", period="5d", status=RunStatus.DUPLICATE_SIGNAL,
                     backend_status_code=409, backend_reason_code="duplicate_signal")


def make_signal_candidate_result(ticker: str = "SPY") -> RunResult:
    return RunResult(
        ticker=ticker, timeframe="15m", period="5d",
        status=RunStatus.SIGNAL_CANDIDATE,
        bar_time=_BAR_TIME,
        client_signal_id="python_atr_generator:0.2b.0:SPY:15m:2026-05-20T14:30:00Z:buy",
        price="450.0000", stop_loss="447.0000", take_profit="456.0000", risk_reward="2.0000",
    )


_MOCK_DB_RETURN = (MagicMock(), MagicMock())


# ── Enabled gate ───────────────────────────────────────────────────────────────

def test_disabled_exits_0() -> None:
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls:
        mock_cls.return_value = make_settings(FORWARD_TESTING_ENABLED=False)
        result = runner.invoke(main, ["--dry-run"])
    assert result.exit_code == 0
    assert "FORWARD_TESTING_ENABLED=false" in result.output


# ── Market hours guard ─────────────────────────────────────────────────────────

def test_market_hours_only_closed_exits_0() -> None:
    runner = CliRunner()
    persist_calls = []
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli.is_market_open", return_value=False), \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist", side_effect=lambda *a, **kw: persist_calls.append(a)):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--market-hours-only", "--dry-run"])
    assert result.exit_code == 0
    assert "Market closed" in result.output


def test_market_hours_only_open_proceeds() -> None:
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli.is_market_open", return_value=True), \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist"), \
         patch("src.forward_testing.cli.run_ticker", return_value=make_no_signal_result()) as mock_run:
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--market-hours-only", "--dry-run"])
    mock_run.assert_called_once()


# ── Default dry-run behaviour ─────────────────────────────────────────────────

def test_no_send_defaults_to_dry_run() -> None:
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist"), \
         patch("src.forward_testing.cli.run_ticker", return_value=make_no_signal_result()) as mock_run:
        mock_cls.return_value = make_settings()
        runner.invoke(main, [])
    _, call_kwargs = mock_run.call_args
    assert call_kwargs.get("dry_run") is True or mock_run.call_args[1].get("dry_run") is True or mock_run.call_args[0][5] is True


def test_send_flag_calls_run_ticker_with_send_true() -> None:
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist"), \
         patch("src.forward_testing.cli.run_ticker", return_value=make_no_signal_result()) as mock_run:
        mock_cls.return_value = make_settings()
        runner.invoke(main, ["--send"])
    mock_run.assert_called_once()
    _, kwargs = mock_run.call_args
    assert kwargs["send"] is True


# ── Exit codes ────────────────────────────────────────────────────────────────

def test_no_error_exits_0() -> None:
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist"), \
         patch("src.forward_testing.cli.run_ticker", return_value=make_no_signal_result()):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--dry-run"])
    assert result.exit_code == 0


def test_error_status_exits_1() -> None:
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist"), \
         patch("src.forward_testing.cli.run_ticker", return_value=make_error_result()):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--dry-run"])
    assert result.exit_code == 1


def test_signal_sent_status_exits_1() -> None:
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist"), \
         patch("src.forward_testing.cli.run_ticker", return_value=make_signal_sent_result()):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--send"])
    assert result.exit_code == 1


def test_risk_rejected_exits_0() -> None:
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist"), \
         patch("src.forward_testing.cli.run_ticker", return_value=make_risk_rejected_result()):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--send"])
    assert result.exit_code == 0


def test_duplicate_signal_exits_0() -> None:
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist"), \
         patch("src.forward_testing.cli.run_ticker", return_value=make_duplicate_result()):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--send"])
    assert result.exit_code == 0


# ── Batch error isolation ─────────────────────────────────────────────────────

def test_one_error_one_success_exits_1() -> None:
    runner = CliRunner()
    side_effects = [make_error_result("SPY"), make_no_signal_result("QQQ")]
    settings = make_settings(FORWARD_TESTING_TICKERS=["SPY", "QQQ"])
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist"), \
         patch("src.forward_testing.cli.run_ticker", side_effect=side_effects) as mock_run:
        mock_cls.return_value = settings
        result = runner.invoke(main, ["--dry-run"])
    assert result.exit_code == 1
    assert mock_run.call_count == 2


def test_db_write_failure_exits_1() -> None:
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist", side_effect=Exception("db error")), \
         patch("src.forward_testing.cli.run_ticker", return_value=make_no_signal_result()):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--dry-run"])
    assert result.exit_code == 1


# ── Flag behaviours ───────────────────────────────────────────────────────────

def test_once_flag_is_no_op() -> None:
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist"), \
         patch("src.forward_testing.cli.run_ticker", return_value=make_no_signal_result()) as mock_run:
        mock_cls.return_value = make_settings()
        result_without = runner.invoke(main, ["--dry-run"])
        result_with = runner.invoke(main, ["--once", "--dry-run"])
    assert result_without.exit_code == result_with.exit_code


def test_tickers_flag_overrides_settings() -> None:
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist"), \
         patch("src.forward_testing.cli.run_ticker", return_value=make_no_signal_result()) as mock_run:
        mock_cls.return_value = make_settings()
        runner.invoke(main, ["--tickers", "NVDA,MSFT", "--dry-run"])
    called_tickers = [c[0][0] for c in mock_run.call_args_list]
    assert "NVDA" in called_tickers
    assert "MSFT" in called_tickers
    assert len(called_tickers) == 2


def test_run_id_shared_across_tickers() -> None:
    runner = CliRunner()
    persist_args = []
    settings = make_settings(FORWARD_TESTING_TICKERS=["SPY", "QQQ"])
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist", side_effect=lambda *a, **kw: persist_args.append(a[0])), \
         patch("src.forward_testing.cli.run_ticker", side_effect=[make_no_signal_result("SPY"), make_no_signal_result("QQQ")]):
        mock_cls.return_value = settings
        runner.invoke(main, ["--dry-run"])
    assert len(persist_args) == 2
    assert persist_args[0] == persist_args[1]


def test_persist_called_with_is_dry_run_true() -> None:
    runner = CliRunner()
    persist_calls = []
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.forward_testing.cli._persist", side_effect=lambda run_id, result, is_dry_run, session: persist_calls.append(is_dry_run)), \
         patch("src.forward_testing.cli.run_ticker", return_value=make_no_signal_result()):
        mock_cls.return_value = make_settings()
        runner.invoke(main, ["--dry-run"])
    assert len(persist_calls) == 1
    assert persist_calls[0] is True
