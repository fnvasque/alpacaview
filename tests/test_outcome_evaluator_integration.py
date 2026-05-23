"""
Integration tests for src.outcome_evaluator.cli.

Uses a real in-memory SQLite DB (StaticPool) with mocked evaluate_signal() and fetch_ohlcv().
Verifies that SignalOutcome rows are actually written, updated, and idempotency is enforced.
"""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.forward_test_run import ForwardTestRun
from app.models.signal_outcome import SignalOutcome
from src.outcome_evaluator.cli import main
from src.outcome_evaluator.evaluator import EvaluationResult, OutcomeStatus

_UTC = timezone.utc
_BAR_TIME = datetime(2026, 5, 20, 14, 30, 0, tzinfo=_UTC)


@pytest.fixture
def mem_db():
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
    s.OUTCOME_EVALUATOR_ENABLED = True
    s.OUTCOME_EVALUATOR_TICKERS = ["SPY"]
    s.OUTCOME_EVALUATOR_TIMEFRAME = "15m"
    s.OUTCOME_EVALUATOR_PERIOD = "5d"
    s.OUTCOME_LOOKAHEAD_BARS = 26
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def seed_forward_test_run(Session, ticker="SPY", csid="test:signal:id", is_dry_run=False):
    session = Session()
    run = ForwardTestRun(
        run_id="run-abc",
        ticker=ticker,
        timeframe="15m",
        period="5d",
        status="signal_candidate",
        is_dry_run=is_dry_run,
        bar_time=_BAR_TIME,
        client_signal_id=csid,
        price="450.0000",
        stop_loss="447.0000",
        take_profit="456.0000",
        risk_reward="2.0000",
    )
    session.add(run)
    session.commit()
    session.close()


def query_outcomes(engine) -> list[SignalOutcome]:
    session = sessionmaker(bind=engine)()
    rows = session.query(SignalOutcome).all()
    session.close()
    return rows


def make_tp_result(csid="test:signal:id") -> EvaluationResult:
    return EvaluationResult(
        client_signal_id=csid,
        ticker="SPY",
        timeframe="15m",
        outcome=OutcomeStatus.TAKE_PROFIT_HIT,
        bars_to_outcome=3,
        pnl_r="2.0000",
        pnl_pct="0.013333",
        outcome_bar_time_utc=datetime(2026, 5, 20, 15, 15, 0, tzinfo=_UTC),
    )


def make_pending_result(csid="test:signal:id") -> EvaluationResult:
    return EvaluationResult(
        client_signal_id=csid,
        ticker="SPY",
        timeframe="15m",
        outcome=OutcomeStatus.PENDING,
        bars_to_outcome=5,
        outcome_bar_time_utc=None,
    )


def run_cli(mem_db, eval_result, flags=None):
    engine, Session = mem_db
    settings = make_settings(engine, Session)
    runner = CliRunner()
    mock_df = MagicMock()

    eval_side: list = [eval_result] if not isinstance(eval_result, list) else eval_result

    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=(engine, Session)), \
         patch("src.outcome_evaluator.cli.fetch_ohlcv", return_value=mock_df), \
         patch("src.outcome_evaluator.cli.evaluate_signal", side_effect=eval_side):
        mock_cls.return_value = settings
        result = runner.invoke(main, flags or [])
    return result


# ── Row written ────────────────────────────────────────────────────────────────

def test_take_profit_hit_row_written(mem_db) -> None:
    engine, Session = mem_db
    seed_forward_test_run(Session)
    run_cli(mem_db, make_tp_result())
    rows = query_outcomes(engine)
    assert len(rows) == 1
    assert rows[0].outcome == "take_profit_hit"
    assert rows[0].pnl_r == "2.0000"
    assert rows[0].client_signal_id == "test:signal:id"


def test_pending_row_written_on_insufficient_bars(mem_db) -> None:
    engine, Session = mem_db
    seed_forward_test_run(Session)
    run_cli(mem_db, make_pending_result())
    rows = query_outcomes(engine)
    assert len(rows) == 1
    assert rows[0].outcome == "pending"
    assert rows[0].outcome_bar_time_utc is None


# ── Re-evaluation ──────────────────────────────────────────────────────────────

def test_pending_row_updated_on_re_evaluation(mem_db) -> None:
    engine, Session = mem_db
    seed_forward_test_run(Session)

    # First run → pending
    run_cli(mem_db, make_pending_result())
    rows = query_outcomes(engine)
    assert rows[0].outcome == "pending"

    # Second run → take_profit_hit
    run_cli(mem_db, make_tp_result())
    rows = query_outcomes(engine)
    assert len(rows) == 1
    assert rows[0].outcome == "take_profit_hit"


def test_terminal_outcome_not_overwritten(mem_db) -> None:
    engine, Session = mem_db
    seed_forward_test_run(Session)

    # First run → take_profit_hit
    run_cli(mem_db, make_tp_result())

    # Second run — attempts pending (should be skipped)
    run_cli(mem_db, make_pending_result())

    rows = query_outcomes(engine)
    assert len(rows) == 1
    assert rows[0].outcome == "take_profit_hit"


# ── Dry-run ────────────────────────────────────────────────────────────────────

def test_dry_run_does_not_write_row(mem_db) -> None:
    engine, Session = mem_db
    seed_forward_test_run(Session)
    run_cli(mem_db, make_tp_result(), flags=["--dry-run"])
    rows = query_outcomes(engine)
    assert len(rows) == 0


# ── --client-signal-id ─────────────────────────────────────────────────────────

def test_client_signal_id_not_found_exits_0(mem_db) -> None:
    engine, Session = mem_db
    # No seeded rows
    settings = make_settings(engine, Session)
    runner = CliRunner()
    with patch("src.outcome_evaluator.cli.OutcomeEvaluatorSettings") as mock_cls, \
         patch("src.outcome_evaluator.cli._init_db", return_value=(engine, Session)):
        mock_cls.return_value = settings
        result = runner.invoke(main, ["--client-signal-id", "nonexistent:id"])
    assert result.exit_code == 0
    assert "no_candidate_found" in result.output


# ── Idempotency ────────────────────────────────────────────────────────────────

def test_idempotency_same_signal_evaluated_twice(mem_db) -> None:
    engine, Session = mem_db
    seed_forward_test_run(Session)

    run_cli(mem_db, make_tp_result())
    run_cli(mem_db, make_tp_result())

    rows = query_outcomes(engine)
    assert len(rows) == 1


# ── Table creation ─────────────────────────────────────────────────────────────

def test_signal_outcomes_table_created_by_init_db(mem_db) -> None:
    engine, _ = mem_db
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    assert "signal_outcomes" in table_names
