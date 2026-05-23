"""
Unit tests for src.signal_generator.cli.

No network, no yfinance. All external calls are mocked.
Uses click.testing.CliRunner for invocation.
"""
import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from src.signal_generator.cli import main
from src.signal_generator.data_fetcher import DataFetchError
from src.signal_generator.indicators import IndicatorResult

_UTC = timezone.utc
_BAR_TIME = datetime(2026, 5, 20, 14, 30, 0, tzinfo=_UTC)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_settings(**overrides) -> MagicMock:
    s = MagicMock()
    s.PYTHON_SIGNAL_GENERATOR_ENABLED = True
    s.SIGNAL_GENERATOR_TICKERS = ["SPY"]
    s.SIGNAL_GENERATOR_TIMEFRAME = "15m"
    s.SIGNAL_GENERATOR_PERIOD = "5d"
    s.SIGNAL_GENERATOR_SECRET = "test-secret"
    s.SIGNAL_GENERATOR_BACKEND_URL = "http://127.0.0.1:8000"
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


def make_payload() -> dict:
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


MOCK_DF = MagicMock()


# ── PYTHON_SIGNAL_GENERATOR_ENABLED gate ──────────────────────────────────────

def test_disabled_exits_0_with_message() -> None:
    runner = CliRunner()
    with patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls:
        mock_cls.return_value = make_settings(PYTHON_SIGNAL_GENERATOR_ENABLED=False)
        result = runner.invoke(main, [])
    assert result.exit_code == 0
    assert "PYTHON_SIGNAL_GENERATOR_ENABLED=false" in result.output


# ── dry-run (default) ─────────────────────────────────────────────────────────

def test_default_is_dry_run_prints_json() -> None:
    runner = CliRunner()
    payload = make_payload()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF),
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()),
        patch("src.signal_generator.cli.build_payload", return_value=payload),
    ):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--ticker", "SPY"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["ticker"] == "SPY"


def test_explicit_dry_run_flag_prints_json() -> None:
    runner = CliRunner()
    payload = make_payload()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF),
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()),
        patch("src.signal_generator.cli.build_payload", return_value=payload),
    ):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--ticker", "SPY", "--dry-run"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["ticker"] == "SPY"


# ── --send ────────────────────────────────────────────────────────────────────

def test_send_flag_posts_to_backend() -> None:
    runner = CliRunner()
    payload = make_payload()
    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.json.return_value = {"approved": True, "signal_id": 1}
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF),
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()),
        patch("src.signal_generator.cli.build_payload", return_value=payload),
        patch("src.signal_generator.cli.requests.post", return_value=mock_resp) as mock_post,
    ):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--ticker", "SPY", "--send"])
    assert result.exit_code == 0
    mock_post.assert_called_once()
    assert "signal accepted" in result.output


def test_send_posts_to_correct_url() -> None:
    runner = CliRunner()
    payload = make_payload()
    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.json.return_value = {"approved": True, "signal_id": 1}
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF),
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()),
        patch("src.signal_generator.cli.build_payload", return_value=payload),
        patch("src.signal_generator.cli.requests.post", return_value=mock_resp) as mock_post,
    ):
        mock_cls.return_value = make_settings()
        runner.invoke(main, ["--ticker", "SPY", "--send"])
    call_url = mock_post.call_args[0][0]
    assert call_url == "http://127.0.0.1:8000/webhook/signal"


def test_send_409_duplicate_exits_0() -> None:
    runner = CliRunner()
    payload = make_payload()
    mock_resp = MagicMock()
    mock_resp.status_code = 409
    mock_resp.json.return_value = {"reason_code": "duplicate_signal"}
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF),
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()),
        patch("src.signal_generator.cli.build_payload", return_value=payload),
        patch("src.signal_generator.cli.requests.post", return_value=mock_resp),
    ):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--ticker", "SPY", "--send"])
    assert result.exit_code == 0
    assert "signal already processed" in result.output


def test_send_4xx_non_duplicate_exits_1() -> None:
    runner = CliRunner()
    payload = make_payload()
    mock_resp = MagicMock()
    mock_resp.status_code = 422
    mock_resp.json.return_value = {"reason_code": "invalid_price", "reason_detail": "price <= 0"}
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF),
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()),
        patch("src.signal_generator.cli.build_payload", return_value=payload),
        patch("src.signal_generator.cli.requests.post", return_value=mock_resp),
    ):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--ticker", "SPY", "--send"])
    assert result.exit_code == 1


# ── --timeframe ───────────────────────────────────────────────────────────────

def test_timeframe_flag_passed_to_fetch() -> None:
    runner = CliRunner()
    payload = make_payload()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF) as mock_fetch,
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()),
        patch("src.signal_generator.cli.build_payload", return_value=payload),
    ):
        mock_cls.return_value = make_settings(SIGNAL_GENERATOR_TIMEFRAME="15m")
        runner.invoke(main, ["--ticker", "SPY", "--timeframe", "5m"])
    _, call_kwargs = mock_fetch.call_args
    # fetch_ohlcv(ticker, period, timeframe) — positional
    assert mock_fetch.call_args[0][2] == "5m"


def test_timeframe_flag_passed_to_compute_indicators() -> None:
    runner = CliRunner()
    payload = make_payload()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF),
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()) as mock_compute,
        patch("src.signal_generator.cli.build_payload", return_value=payload),
    ):
        mock_cls.return_value = make_settings(SIGNAL_GENERATOR_TIMEFRAME="15m")
        runner.invoke(main, ["--ticker", "SPY", "--timeframe", "5m"])
    # compute_indicators(df, ticker, timeframe, ema, atr) — positional
    assert mock_compute.call_args[0][2] == "5m"


def test_timeframe_defaults_to_settings_when_not_passed() -> None:
    runner = CliRunner()
    payload = make_payload()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF) as mock_fetch,
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()),
        patch("src.signal_generator.cli.build_payload", return_value=payload),
    ):
        mock_cls.return_value = make_settings(SIGNAL_GENERATOR_TIMEFRAME="1h")
        runner.invoke(main, ["--ticker", "SPY"])
    assert mock_fetch.call_args[0][2] == "1h"


# ── --period ──────────────────────────────────────────────────────────────────

def test_period_flag_passed_to_fetch() -> None:
    runner = CliRunner()
    payload = make_payload()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF) as mock_fetch,
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()),
        patch("src.signal_generator.cli.build_payload", return_value=payload),
    ):
        mock_cls.return_value = make_settings(SIGNAL_GENERATOR_PERIOD="5d")
        runner.invoke(main, ["--ticker", "SPY", "--period", "60d"])
    # fetch_ohlcv(ticker, period, timeframe)
    assert mock_fetch.call_args[0][1] == "60d"


def test_period_defaults_to_settings_when_not_passed() -> None:
    runner = CliRunner()
    payload = make_payload()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF) as mock_fetch,
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()),
        patch("src.signal_generator.cli.build_payload", return_value=payload),
    ):
        mock_cls.return_value = make_settings(SIGNAL_GENERATOR_PERIOD="30d")
        runner.invoke(main, ["--ticker", "SPY"])
    assert mock_fetch.call_args[0][1] == "30d"


# ── --force ───────────────────────────────────────────────────────────────────

def test_force_bypasses_no_crossover() -> None:
    runner = CliRunner()
    payload = make_payload()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF),
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result(crossover=False)),
        patch("src.signal_generator.cli.build_payload", return_value=payload),
    ):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--ticker", "SPY", "--force"])
    assert result.exit_code == 0
    assert "no crossover" not in result.output


def test_no_crossover_without_force_skips() -> None:
    runner = CliRunner()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF),
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result(crossover=False)),
    ):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--ticker", "SPY"])
    assert result.exit_code == 0
    assert "no crossover" in result.output


# ── --ticker ──────────────────────────────────────────────────────────────────

def test_ticker_flag_runs_only_that_ticker() -> None:
    runner = CliRunner()
    payload = make_payload()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF) as mock_fetch,
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()),
        patch("src.signal_generator.cli.build_payload", return_value=payload),
    ):
        mock_cls.return_value = make_settings(SIGNAL_GENERATOR_TICKERS=["SPY", "QQQ", "AAPL"])
        runner.invoke(main, ["--ticker", "nvda"])
    assert mock_fetch.call_count == 1
    assert mock_fetch.call_args[0][0] == "NVDA"


def test_no_ticker_flag_runs_all_settings_tickers() -> None:
    runner = CliRunner()
    payload = make_payload()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF),
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()),
        patch("src.signal_generator.cli.build_payload", return_value=payload),
    ):
        mock_cls.return_value = make_settings(SIGNAL_GENERATOR_TICKERS=["SPY", "QQQ"])
        result = runner.invoke(main, [])
    assert result.exit_code == 0


# ── error paths ───────────────────────────────────────────────────────────────

def test_fetch_error_exits_1() -> None:
    runner = CliRunner()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", side_effect=DataFetchError("network timeout")),
    ):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--ticker", "SPY"])
    assert result.exit_code == 1
    assert "fetch failed" in result.output


def test_insufficient_data_logs_and_continues() -> None:
    runner = CliRunner()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF),
        patch("src.signal_generator.cli.compute_indicators", return_value=None),
    ):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--ticker", "SPY"])
    assert result.exit_code == 0
    assert "no_signal" in result.output


def test_stop_loss_zero_skips_ticker() -> None:
    runner = CliRunner()
    with (
        patch("src.signal_generator.cli.SignalGeneratorSettings") as mock_cls,
        patch("src.signal_generator.cli.fetch_ohlcv", return_value=MOCK_DF),
        patch("src.signal_generator.cli.compute_indicators", return_value=make_indicator_result()),
        patch("src.signal_generator.cli.build_payload", return_value=None),
    ):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--ticker", "SPY", "--force"])
    assert result.exit_code == 0
    assert "stop_loss" in result.output
