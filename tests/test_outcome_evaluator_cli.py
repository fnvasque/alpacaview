"""
Unit tests for src.outcome_evaluator.cli.

No real network, no real DB. All external calls are mocked.
Uses click.testing.CliRunner for invocation.
"""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest
from click.testing import CliRunner

from src.outcome_evaluator.cli import main
from src.outcome_evaluator.evaluator import EvaluationResult, OutcomeStatus

_UTC = timezone.utc
_BAR_TIME = datetime(2026, 5, 20, 14, 30, 0, tzinfo=_UTC)
_MOCK_DB_RETURN = (MagicMock(), MagicMock())


def make_settings(**overrides) -> MagicMock:
    s = MagicMock()
    s.OUTCOME_EVALUATOR_ENABLED = True
    s.OUTCOME_EVALUATOR_TICKERS = ["SPY"]
    s.OUTCOME_EVALUATOR_TIMEFRAME = "15m"
    s.OUTCOME_EVALUATOR_PERIOD = "5d"
    s.OUTCOME_LOOKAHEAD_BARS = 26
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def make_source_row(ticker: str = "SPY", csid: str = "test:id") -> MagicMock:
    row = MagicMock()
    row.ticker = ticker
    row.client_signal_id = csid
    row.timeframe = "15m"
    row.price = "450.0000"
    row.stop_loss = "447.0000"
    row.take_profit = "456.0000"
    row.risk_reward = "2.0000"
    row.bar_time = _BAR_TIME
    row.status = "signal_candidate"
    row.is_dry_run = False
    return row


def make_tp_result(csid: str = "test:id") -> EvaluationResult:
    return EvaluationResult(
        client_signal_id=csid,
        ticker="SPY",
        timeframe="15m",
        outcome=OutcomeStatus.TAKE_PROFIT_HIT,
        bars_to_outcome=3,
        pnl_r="2.0000",
        pnl_pct="0.013333",
    )


def make_pending_result(csid: str = "test:id") -> EvaluationResult:
    return EvaluationResult(
        client_signal_id=csid,
        ticker="SPY",
        timeframe="15m",
        outcome=OutcomeStatus.PENDING,
        bars_to_outcome=5,
    )


# ── Enabled gate ───────────────────────────────────────────────────────────────

def test_disabled_exits_0() -> None:
    runner = CliRunner()
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls:
        mock_cls.return_value = make_settings(OUTCOME_EVALUATOR_ENABLED=False)
        result = runner.invoke(main, ["--dry-run"])
    assert result.exit_code == 0
    assert "OUTCOME_EVALUATOR_ENABLED=false" in result.output


# ── No signals ────────────────────────────────────────────────────────────────

def test_no_signals_exits_0() -> None:
    runner = CliRunner()
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_signals", return_value=[]):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--dry-run"])
    assert result.exit_code == 0


# ── Exit codes ────────────────────────────────────────────────────────────────

def test_take_profit_hit_exits_0() -> None:
    runner = CliRunner()
    source_row = make_source_row()
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_signals", return_value=[source_row]), \
         patch("src.outcome_evaluator.cli._get_existing_outcome", return_value=None), \
         patch("src.outcome_evaluator.cli.fetch_ohlcv", return_value=MagicMock()), \
         patch("src.outcome_evaluator.cli.evaluate_signal", return_value=make_tp_result()), \
         patch("src.outcome_evaluator.cli._upsert"):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--send"] if False else [])
    assert result.exit_code == 0


def test_error_exits_1() -> None:
    from src.signal_generator.data_fetcher import DataFetchError
    runner = CliRunner()
    source_row = make_source_row()
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_signals", return_value=[source_row]), \
         patch("src.outcome_evaluator.cli._get_existing_outcome", return_value=None), \
         patch("src.outcome_evaluator.cli.fetch_ohlcv", side_effect=DataFetchError("network fail")):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--dry-run"])
    assert result.exit_code == 1


# ── Idempotency ────────────────────────────────────────────────────────────────

def test_terminal_outcome_skipped() -> None:
    runner = CliRunner()
    source_row = make_source_row()
    existing = MagicMock()
    existing.outcome = "take_profit_hit"

    upsert_calls = []
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_signals", return_value=[source_row]), \
         patch("src.outcome_evaluator.cli._get_existing_outcome", return_value=existing), \
         patch("src.outcome_evaluator.cli.fetch_ohlcv", return_value=MagicMock()), \
         patch("src.outcome_evaluator.cli._upsert", side_effect=lambda *a, **kw: upsert_calls.append(a)):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--dry-run"])

    assert result.exit_code == 0
    assert len(upsert_calls) == 0


def test_pending_outcome_reevaluated() -> None:
    runner = CliRunner()
    source_row = make_source_row()
    existing = MagicMock()
    existing.outcome = "pending"

    upsert_calls = []
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_signals", return_value=[source_row]), \
         patch("src.outcome_evaluator.cli._get_existing_outcome", return_value=existing), \
         patch("src.outcome_evaluator.cli.fetch_ohlcv", return_value=MagicMock()), \
         patch("src.outcome_evaluator.cli.evaluate_signal", return_value=make_tp_result()), \
         patch("src.outcome_evaluator.cli._upsert", side_effect=lambda *a, **kw: upsert_calls.append(a)):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, [])

    assert len(upsert_calls) == 1


# ── Dry-run ────────────────────────────────────────────────────────────────────

def test_dry_run_does_not_call_upsert() -> None:
    runner = CliRunner()
    source_row = make_source_row()
    upsert_calls = []
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_signals", return_value=[source_row]), \
         patch("src.outcome_evaluator.cli._get_existing_outcome", return_value=None), \
         patch("src.outcome_evaluator.cli.fetch_ohlcv", return_value=MagicMock()), \
         patch("src.outcome_evaluator.cli.evaluate_signal", return_value=make_tp_result()), \
         patch("src.outcome_evaluator.cli._upsert", side_effect=lambda *a, **kw: upsert_calls.append(a)):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--dry-run"])
    assert result.exit_code == 0
    assert len(upsert_calls) == 0


# ── Flag behaviours ───────────────────────────────────────────────────────────

def test_once_flag_is_no_op() -> None:
    runner = CliRunner()
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_signals", return_value=[]):
        mock_cls.return_value = make_settings()
        result_without = runner.invoke(main, ["--dry-run"])
        result_with = runner.invoke(main, ["--once", "--dry-run"])
    assert result_without.exit_code == result_with.exit_code


def test_include_dry_run_flag_passed_to_query() -> None:
    runner = CliRunner()
    query_calls: list = []
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_signals", side_effect=lambda *a, **kw: query_calls.append((a, kw)) or []):
        mock_cls.return_value = make_settings()
        runner.invoke(main, ["--include-dry-run", "--dry-run"])
    assert len(query_calls) == 1
    _, kwargs = query_calls[0]
    # include_dry_run is the 3rd positional argument
    assert kwargs.get("include_dry_run") is True or query_calls[0][0][2] is True


def test_client_signal_id_calls_single_query() -> None:
    runner = CliRunner()
    single_calls: list = []
    multi_calls: list = []
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_single_signal", side_effect=lambda *a, **kw: single_calls.append(a) or []) as mock_single, \
         patch("src.outcome_evaluator.cli._query_signals", side_effect=lambda *a, **kw: multi_calls.append(a) or []):
        mock_cls.return_value = make_settings()
        runner.invoke(main, ["--client-signal-id", "some:id", "--dry-run"])
    assert len(single_calls) == 1
    assert len(multi_calls) == 0


def test_client_signal_id_not_found_exits_0() -> None:
    runner = CliRunner()
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_single_signal", return_value=[]):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, ["--client-signal-id", "unknown:id"])
    assert result.exit_code == 0
    assert "no_candidate_found" in result.output


def test_lookahead_bars_override() -> None:
    runner = CliRunner()
    source_row = make_source_row()
    eval_calls: list = []
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_signals", return_value=[source_row]), \
         patch("src.outcome_evaluator.cli._get_existing_outcome", return_value=None), \
         patch("src.outcome_evaluator.cli.fetch_ohlcv", return_value=MagicMock()), \
         patch("src.outcome_evaluator.cli.evaluate_signal",
               side_effect=lambda **kw: eval_calls.append(kw) or make_tp_result()), \
         patch("src.outcome_evaluator.cli._upsert"):
        mock_cls.return_value = make_settings()
        runner.invoke(main, ["--lookahead-bars", "10", "--dry-run"])
    assert len(eval_calls) == 1
    assert eval_calls[0]["lookahead_bars"] == 10


def test_tickers_flag_override() -> None:
    runner = CliRunner()
    query_calls: list = []
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_signals", side_effect=lambda *a, **kw: query_calls.append((a, kw)) or []):
        mock_cls.return_value = make_settings()
        runner.invoke(main, ["--tickers", "NVDA", "--dry-run"])
    assert len(query_calls) == 1
    # tickers is the 2nd positional argument after session
    called_tickers = query_calls[0][0][1]
    assert called_tickers == ["NVDA"]


def test_multiple_tickers_one_fetch_per_ticker() -> None:
    runner = CliRunner()
    row_spy = make_source_row("SPY", "spy:id")
    row_qqq = make_source_row("QQQ", "qqq:id")
    fetch_calls: list = []
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_signals", return_value=[row_spy, row_qqq]), \
         patch("src.outcome_evaluator.cli._get_existing_outcome", return_value=None), \
         patch("src.outcome_evaluator.cli.fetch_ohlcv",
               side_effect=lambda *a, **kw: fetch_calls.append(a) or MagicMock()), \
         patch("src.outcome_evaluator.cli.evaluate_signal", return_value=make_pending_result()), \
         patch("src.outcome_evaluator.cli._upsert"):
        mock_cls.return_value = make_settings(OUTCOME_EVALUATOR_TICKERS=["SPY", "QQQ"])
        runner.invoke(main, ["--dry-run"])
    assert len(fetch_calls) == 2
    fetched_tickers = [c[0] for c in fetch_calls]
    assert "SPY" in fetched_tickers
    assert "QQQ" in fetched_tickers


def test_upsert_failure_exits_1() -> None:
    runner = CliRunner()
    source_row = make_source_row()
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=_MOCK_DB_RETURN), \
         patch("src.outcome_evaluator.cli._query_signals", return_value=[source_row]), \
         patch("src.outcome_evaluator.cli._get_existing_outcome", return_value=None), \
         patch("src.outcome_evaluator.cli.fetch_ohlcv", return_value=MagicMock()), \
         patch("src.outcome_evaluator.cli.evaluate_signal", return_value=make_tp_result()), \
         patch("src.outcome_evaluator.cli._upsert", side_effect=Exception("db error")):
        mock_cls.return_value = make_settings()
        result = runner.invoke(main, [])
    assert result.exit_code == 1
