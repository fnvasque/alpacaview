"""
Unit tests for src.reporting.metrics.

No network, no Streamlit. Uses StaticPool in-memory SQLite.
"""
from datetime import date, datetime, timezone
from typing import Optional

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.database import Base
from app.models.forward_test_run import ForwardTestRun
from app.models.signal_outcome import SignalOutcome
from src.reporting.metrics import (
    BlockedSignalMetrics,
    DailyMetrics,
    FilterParams,
    GlobalMetrics,
    TickerMetrics,
    compute_blocked_signals,
    compute_daily_evolution,
    compute_global_metrics,
    compute_ticker_metrics,
)

_UTC = timezone.utc
_T0 = datetime(2026, 5, 20, 14, 30, 0, tzinfo=_UTC)
_T1 = datetime(2026, 5, 21, 14, 30, 0, tzinfo=_UTC)


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


def seed_ftr(
    Session,
    ticker: str = "SPY",
    status: str = "signal_candidate",
    client_signal_id: str = "sig:001",
    is_dry_run: bool = False,
    backend_reason_code: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> ForwardTestRun:
    session = Session()
    row = ForwardTestRun(
        run_id="run-001",
        ticker=ticker,
        timeframe="15m",
        period="5d",
        status=status,
        is_dry_run=is_dry_run,
        client_signal_id=client_signal_id,
        backend_reason_code=backend_reason_code,
        created_at_utc=created_at or _T0,
    )
    session.add(row)
    session.commit()
    session.close()
    return row


def seed_so(
    Session,
    client_signal_id: str = "sig:001",
    ticker: str = "SPY",
    outcome: str = "take_profit_hit",
    pnl_r: Optional[str] = None,
    pnl_pct: Optional[str] = None,
    is_dry_run_source: bool = False,
    created_at: Optional[datetime] = None,
) -> SignalOutcome:
    session = Session()
    row = SignalOutcome(
        client_signal_id=client_signal_id,
        ticker=ticker,
        timeframe="15m",
        entry_price="450.0000",
        stop_loss="447.0000",
        take_profit="456.0000",
        bar_time=_T0,
        forward_test_run_status="signal_candidate",
        is_dry_run_source=is_dry_run_source,
        outcome=outcome,
        pnl_r=pnl_r,
        pnl_pct=pnl_pct,
        created_at_utc=created_at or _T0,
    )
    session.add(row)
    session.commit()
    session.close()
    return row


def _session(mem_db):
    engine, Session = mem_db
    return Session()


# ── GlobalMetrics ──────────────────────────────────────────────────────────────

def test_global_metrics_empty_db(mem_db) -> None:
    engine, Session = mem_db
    session = Session()
    metrics = compute_global_metrics(session, FilterParams())
    session.close()
    assert metrics.total_signals == 0
    assert metrics.evaluated_signals == 0
    assert metrics.win_rate is None
    assert metrics.avg_r is None
    assert metrics.total_r is None


def test_total_signals_distinct_client_signal_id(mem_db) -> None:
    engine, Session = mem_db
    seed_ftr(Session, client_signal_id="sig:dup", status="signal_candidate")
    seed_ftr(Session, client_signal_id="sig:dup", status="risk_approved")
    session = Session()
    metrics = compute_global_metrics(session, FilterParams())
    session.close()
    assert metrics.total_signals == 1


def test_total_signals_excludes_no_signal(mem_db) -> None:
    engine, Session = mem_db
    seed_ftr(Session, status="no_signal")
    session = Session()
    metrics = compute_global_metrics(session, FilterParams())
    session.close()
    assert metrics.total_signals == 0


def test_total_signals_excludes_skipped_market_closed(mem_db) -> None:
    engine, Session = mem_db
    seed_ftr(Session, status="skipped_market_closed")
    session = Session()
    metrics = compute_global_metrics(session, FilterParams())
    session.close()
    assert metrics.total_signals == 0


def test_evaluated_signals_excludes_pending(mem_db) -> None:
    engine, Session = mem_db
    seed_so(Session, outcome="pending")
    session = Session()
    metrics = compute_global_metrics(session, FilterParams())
    session.close()
    assert metrics.evaluated_signals == 0
    assert metrics.pending_signals == 1


def test_win_rate_three_tp_one_sl(mem_db) -> None:
    engine, Session = mem_db
    for i in range(3):
        seed_so(Session, client_signal_id=f"sig:tp:{i}", outcome="take_profit_hit")
    seed_so(Session, client_signal_id="sig:sl:0", outcome="stop_loss_hit")
    session = Session()
    metrics = compute_global_metrics(session, FilterParams())
    session.close()
    assert metrics.win_rate == pytest.approx(0.75)


def test_win_rate_none_when_no_terminal_outcomes(mem_db) -> None:
    engine, Session = mem_db
    seed_so(Session, outcome="pending")
    session = Session()
    metrics = compute_global_metrics(session, FilterParams())
    session.close()
    assert metrics.win_rate is None


def test_win_rate_zero_sl(mem_db) -> None:
    engine, Session = mem_db
    for i in range(3):
        seed_so(Session, client_signal_id=f"sig:tp:{i}", outcome="take_profit_hit")
    session = Session()
    metrics = compute_global_metrics(session, FilterParams())
    session.close()
    assert metrics.win_rate == pytest.approx(1.0)


def test_avg_r_excludes_null(mem_db) -> None:
    engine, Session = mem_db
    seed_so(Session, client_signal_id="sig:001", outcome="take_profit_hit", pnl_r="2.0000")
    seed_so(Session, client_signal_id="sig:002", outcome="pending", pnl_r=None)
    session = Session()
    metrics = compute_global_metrics(session, FilterParams())
    session.close()
    assert metrics.avg_r == pytest.approx(2.0)


def test_total_r_sum(mem_db) -> None:
    engine, Session = mem_db
    seed_so(Session, client_signal_id="sig:001", outcome="take_profit_hit", pnl_r="2.0000")
    seed_so(Session, client_signal_id="sig:002", outcome="stop_loss_hit", pnl_r="-1.0000")
    session = Session()
    metrics = compute_global_metrics(session, FilterParams())
    session.close()
    assert metrics.total_r == pytest.approx(1.0)


def test_avg_pnl_pct_calculation(mem_db) -> None:
    engine, Session = mem_db
    seed_so(Session, client_signal_id="sig:001", outcome="take_profit_hit", pnl_pct="0.013333")
    seed_so(Session, client_signal_id="sig:002", outcome="stop_loss_hit", pnl_pct="-0.006667")
    session = Session()
    metrics = compute_global_metrics(session, FilterParams())
    session.close()
    assert metrics.avg_pnl_pct == pytest.approx(0.003333, abs=1e-5)


# ── TickerMetrics ──────────────────────────────────────────────────────────────

def test_ticker_metrics_groups_by_ticker(mem_db) -> None:
    engine, Session = mem_db
    seed_so(Session, client_signal_id="sig:001", ticker="SPY", outcome="take_profit_hit")
    seed_so(Session, client_signal_id="sig:002", ticker="QQQ", outcome="stop_loss_hit")
    session = Session()
    result = compute_ticker_metrics(session, FilterParams())
    session.close()
    tickers = [m.ticker for m in result]
    assert "QQQ" in tickers
    assert "SPY" in tickers
    assert len(result) == 2


# ── BlockedSignalMetrics ───────────────────────────────────────────────────────

def test_blocked_signals_risk_rejected_only(mem_db) -> None:
    engine, Session = mem_db
    seed_ftr(Session, status="risk_rejected", backend_reason_code="MAX_DAILY_TRADES")
    session = Session()
    metrics = compute_blocked_signals(session, FilterParams())
    session.close()
    assert metrics.total_rejected == 1


def test_blocked_signals_excludes_duplicate_signal(mem_db) -> None:
    engine, Session = mem_db
    seed_ftr(Session, status="duplicate_signal")
    session = Session()
    metrics = compute_blocked_signals(session, FilterParams())
    session.close()
    assert metrics.total_rejected == 0


def test_blocked_signals_by_reason_code(mem_db) -> None:
    engine, Session = mem_db
    seed_ftr(Session, client_signal_id="sig:001", status="risk_rejected", backend_reason_code="MAX_DAILY_TRADES")
    seed_ftr(Session, client_signal_id="sig:002", status="risk_rejected", backend_reason_code="KILL_SWITCH")
    session = Session()
    metrics = compute_blocked_signals(session, FilterParams())
    session.close()
    assert len(metrics.by_reason_code) == 2
    assert metrics.by_reason_code["MAX_DAILY_TRADES"] == 1
    assert metrics.by_reason_code["KILL_SWITCH"] == 1


def test_blocked_signals_null_reason_code_mapped_to_unknown(mem_db) -> None:
    engine, Session = mem_db
    seed_ftr(Session, status="risk_rejected", backend_reason_code=None)
    session = Session()
    metrics = compute_blocked_signals(session, FilterParams())
    session.close()
    assert "unknown" in metrics.by_reason_code
    assert metrics.by_reason_code["unknown"] == 1


# ── DailyMetrics ──────────────────────────────────────────────────────────────

def test_daily_evolution_groups_by_date(mem_db) -> None:
    engine, Session = mem_db
    seed_ftr(Session, client_signal_id="sig:001", created_at=_T0)
    seed_ftr(Session, client_signal_id="sig:002", created_at=_T1)
    session = Session()
    result = compute_daily_evolution(session, FilterParams())
    session.close()
    assert len(result) == 2
    assert result[0].date < result[1].date


# ── Filter tests ──────────────────────────────────────────────────────────────

def test_filter_by_ticker(mem_db) -> None:
    engine, Session = mem_db
    seed_so(Session, client_signal_id="sig:spy", ticker="SPY", outcome="take_profit_hit")
    seed_so(Session, client_signal_id="sig:qqq", ticker="QQQ", outcome="take_profit_hit")
    session = Session()
    metrics = compute_global_metrics(session, FilterParams(tickers=["SPY"]))
    session.close()
    assert metrics.take_profit_hits == 1


def test_filter_by_date_range(mem_db) -> None:
    engine, Session = mem_db
    seed_so(Session, client_signal_id="sig:old", outcome="take_profit_hit", created_at=_T0)
    seed_so(Session, client_signal_id="sig:new", outcome="stop_loss_hit", created_at=_T1)
    session = Session()
    metrics = compute_global_metrics(
        session,
        FilterParams(start_date=date(2026, 5, 21), end_date=date(2026, 5, 21)),
    )
    session.close()
    assert metrics.stop_loss_hits == 1
    assert metrics.take_profit_hits == 0


def test_dry_run_excluded_by_default(mem_db) -> None:
    engine, Session = mem_db
    seed_so(Session, outcome="take_profit_hit", is_dry_run_source=True)
    session = Session()
    metrics = compute_global_metrics(session, FilterParams())
    session.close()
    assert metrics.take_profit_hits == 0


def test_dry_run_included_when_flag_set(mem_db) -> None:
    engine, Session = mem_db
    seed_so(Session, outcome="take_profit_hit", is_dry_run_source=True)
    session = Session()
    metrics = compute_global_metrics(session, FilterParams(include_dry_run=True))
    session.close()
    assert metrics.take_profit_hits == 1
