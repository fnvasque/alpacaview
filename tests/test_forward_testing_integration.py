"""
Integration tests for src.forward_testing.cli.

Uses a real in-memory SQLite DB (StaticPool) with mocked run_ticker().
Verifies that ForwardTestRun rows are actually written and readable.
"""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — ensures all models registered before create_all
from app.database import Base
from app.models.forward_test_run import ForwardTestRun
from src.forward_testing.cli import main
from src.forward_testing.runner import RunResult, RunStatus

_UTC = timezone.utc
_BAR_TIME = datetime(2026, 5, 20, 14, 30, 0, tzinfo=_UTC)


@pytest.fixture
def mem_db():
    """Create a real in-memory SQLite DB shared via StaticPool."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield engine, Session
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def make_settings(engine, Session, **overrides) -> MagicMock:
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


def run_cli(mem_db, run_ticker_result, flags=None, tickers=None):
    engine, Session = mem_db
    if tickers is not None:
        settings = make_settings(engine, Session, FORWARD_TESTING_TICKERS=tickers)
    else:
        settings = make_settings(engine, Session)

    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings") as mock_cls, \
         patch("src.forward_testing.cli._init_db", return_value=(engine, Session)), \
         patch("src.forward_testing.cli.run_ticker", return_value=run_ticker_result) \
         if not isinstance(run_ticker_result, list) else \
         patch("src.forward_testing.cli.run_ticker", side_effect=run_ticker_result):
        mock_cls.return_value = settings
        result = runner.invoke(main, flags or ["--dry-run"])
    return result


def query_rows(engine):
    session = sessionmaker(bind=engine)()
    rows = session.query(ForwardTestRun).all()
    session.close()
    return rows


# ── Row written ────────────────────────────────────────────────────────────────

def test_forward_test_run_row_written_to_db(mem_db) -> None:
    engine, Session = mem_db
    run_result = RunResult(
        ticker="SPY", timeframe="15m", period="5d",
        status=RunStatus.SIGNAL_CANDIDATE,
        bar_time=_BAR_TIME,
        client_signal_id="python_atr_generator:0.2b.0:SPY:15m:2026-05-20T14:30:00Z:buy",
        price="450.0000", stop_loss="447.0000", take_profit="456.0000", risk_reward="2.0000",
    )
    runner = CliRunner()
    settings = make_settings(engine, Session)
    with patch("src.forward_testing.cli.ForwardTestingSettings", return_value=settings), \
         patch("src.forward_testing.cli._init_db", return_value=(engine, Session)), \
         patch("src.forward_testing.cli.run_ticker", return_value=run_result):
        runner.invoke(main, ["--dry-run"])

    rows = query_rows(engine)
    assert len(rows) == 1
    row = rows[0]
    assert row.ticker == "SPY"
    assert row.status == "signal_candidate"
    assert row.price == "450.0000"
    assert row.client_signal_id is not None


def test_no_signal_row_written_with_correct_status(mem_db) -> None:
    engine, Session = mem_db
    run_result = RunResult(ticker="SPY", timeframe="15m", period="5d", status=RunStatus.NO_SIGNAL)
    settings = make_settings(engine, Session)
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings", return_value=settings), \
         patch("src.forward_testing.cli._init_db", return_value=(engine, Session)), \
         patch("src.forward_testing.cli.run_ticker", return_value=run_result):
        runner.invoke(main, ["--dry-run"])

    rows = query_rows(engine)
    assert len(rows) == 1
    assert rows[0].status == "no_signal"


def test_is_dry_run_column_true_on_dry_run(mem_db) -> None:
    engine, Session = mem_db
    run_result = RunResult(ticker="SPY", timeframe="15m", period="5d", status=RunStatus.NO_SIGNAL)
    settings = make_settings(engine, Session)
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings", return_value=settings), \
         patch("src.forward_testing.cli._init_db", return_value=(engine, Session)), \
         patch("src.forward_testing.cli.run_ticker", return_value=run_result):
        runner.invoke(main, ["--dry-run"])

    rows = query_rows(engine)
    assert rows[0].is_dry_run is True


def test_is_dry_run_column_false_on_send(mem_db) -> None:
    engine, Session = mem_db
    run_result = RunResult(
        ticker="SPY", timeframe="15m", period="5d",
        status=RunStatus.RISK_APPROVED,
        backend_status_code=202, backend_approved=True,
    )
    settings = make_settings(engine, Session)
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings", return_value=settings), \
         patch("src.forward_testing.cli._init_db", return_value=(engine, Session)), \
         patch("src.forward_testing.cli.run_ticker", return_value=run_result):
        runner.invoke(main, ["--send"])

    rows = query_rows(engine)
    assert rows[0].is_dry_run is False


def test_run_id_consistent_across_multiple_tickers(mem_db) -> None:
    engine, Session = mem_db
    settings = make_settings(engine, Session, FORWARD_TESTING_TICKERS=["SPY", "QQQ"])
    side_effects = [
        RunResult(ticker="SPY", timeframe="15m", period="5d", status=RunStatus.NO_SIGNAL),
        RunResult(ticker="QQQ", timeframe="15m", period="5d", status=RunStatus.NO_SIGNAL),
    ]
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings", return_value=settings), \
         patch("src.forward_testing.cli._init_db", return_value=(engine, Session)), \
         patch("src.forward_testing.cli.run_ticker", side_effect=side_effects):
        runner.invoke(main, ["--dry-run"])

    rows = query_rows(engine)
    assert len(rows) == 2
    assert rows[0].run_id == rows[1].run_id


def test_error_row_has_error_message(mem_db) -> None:
    engine, Session = mem_db
    run_result = RunResult(
        ticker="SPY", timeframe="15m", period="5d",
        status=RunStatus.ERROR, error_message="fetch failed",
    )
    settings = make_settings(engine, Session)
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings", return_value=settings), \
         patch("src.forward_testing.cli._init_db", return_value=(engine, Session)), \
         patch("src.forward_testing.cli.run_ticker", return_value=run_result):
        runner.invoke(main, ["--dry-run"])

    rows = query_rows(engine)
    assert rows[0].status == "error"
    assert rows[0].error_message == "fetch failed"


def test_skipped_market_closed_rows_written(mem_db) -> None:
    engine, Session = mem_db
    settings = make_settings(engine, Session)
    runner = CliRunner()
    with patch("src.forward_testing.cli.ForwardTestingSettings", return_value=settings), \
         patch("src.forward_testing.cli._init_db", return_value=(engine, Session)), \
         patch("src.forward_testing.cli.is_market_open", return_value=False):
        runner.invoke(main, ["--market-hours-only", "--dry-run"])

    rows = query_rows(engine)
    assert len(rows) == 1
    assert rows[0].status == "skipped_market_closed"


def test_forward_test_runs_table_created_by_init_db(mem_db) -> None:
    engine, _ = mem_db
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    assert "forward_test_runs" in table_names
