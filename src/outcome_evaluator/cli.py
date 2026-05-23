import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import click
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — registers all models in Base.metadata
from app.database import Base
from app.models.forward_test_run import ForwardTestRun
from app.models.signal_outcome import SignalOutcome
from src.signal_generator.data_fetcher import DataFetchError, fetch_ohlcv
from src.outcome_evaluator.config import OutcomeEvaluatorSettings
from src.outcome_evaluator.evaluator import (
    TERMINAL_OUTCOMES,
    EvaluationResult,
    OutcomeStatus,
    evaluate_signal,
)

EVALUABLE_STATUSES: tuple[str, ...] = (
    "signal_candidate",
    "risk_approved",
    "risk_rejected",
    "duplicate_signal",
)


@click.command()
@click.option("--once", is_flag=True, default=False, help="No-op flag for cron/launchd readability.")
@click.option("--tickers", default=None, help="Comma-separated tickers. Overrides OUTCOME_EVALUATOR_TICKERS.")
@click.option("--timeframe", default=None, help="Timeframe. Overrides OUTCOME_EVALUATOR_TIMEFRAME.")
@click.option("--period", default=None, help="yfinance period. Overrides OUTCOME_EVALUATOR_PERIOD.")
@click.option("--lookahead-bars", "lookahead_bars", type=int, default=None, help="Bars to evaluate. Overrides OUTCOME_LOOKAHEAD_BARS.")
@click.option("--include-dry-run", "include_dry_run", is_flag=True, default=False, help="Include signals from dry-run forward-test rows.")
@click.option("--client-signal-id", "client_signal_id", default=None, help="Evaluate a single signal by ID.")
@click.option("--dry-run", "dry_run", is_flag=True, default=False, help="Evaluate but do not write to DB.")
def main(
    once: bool,
    tickers: Optional[str],
    timeframe: Optional[str],
    period: Optional[str],
    lookahead_bars: Optional[int],
    include_dry_run: bool,
    client_signal_id: Optional[str],
    dry_run: bool,
) -> None:
    settings = OutcomeEvaluatorSettings()

    if not settings.OUTCOME_EVALUATOR_ENABLED:
        click.echo("OUTCOME_EVALUATOR_ENABLED=false — skipping.")
        sys.exit(0)

    engine, Session = _init_db(settings.OUTCOME_EVALUATOR_DB_URL)
    db_session = Session()

    resolved_tickers = _parse_tickers(tickers) or settings.OUTCOME_EVALUATOR_TICKERS
    resolved_timeframe = timeframe or settings.OUTCOME_EVALUATOR_TIMEFRAME
    resolved_period = period or settings.OUTCOME_EVALUATOR_PERIOD
    resolved_lookahead = lookahead_bars if lookahead_bars is not None else settings.OUTCOME_LOOKAHEAD_BARS

    if client_signal_id is not None:
        source_rows = _query_single_signal(db_session, client_signal_id, include_dry_run)
        if not source_rows:
            click.echo(f"no_candidate_found: {client_signal_id}")
            db_session.close()
            sys.exit(0)
    else:
        source_rows = _query_signals(db_session, resolved_tickers, include_dry_run)

    by_ticker: dict[str, list[ForwardTestRun]] = defaultdict(list)
    for row in source_rows:
        by_ticker[row.ticker].append(row)

    has_error = False

    for ticker, ticker_rows in by_ticker.items():
        # Idempotency pre-filter: skip if all rows for this ticker already have terminal outcomes
        pending_rows = [
            r for r in ticker_rows
            if not _is_terminal_in_db(db_session, r.client_signal_id)
        ]
        if not pending_rows:
            for r in ticker_rows:
                _echo_skipped(r.client_signal_id)
            continue

        try:
            df = fetch_ohlcv(ticker, resolved_period, resolved_timeframe)
        except DataFetchError as exc:
            click.echo(f"[{ticker}] fetch failed: {exc}", err=True)
            has_error = True
            continue
        except Exception as exc:
            click.echo(f"[{ticker}] fetch failed: {exc}", err=True)
            has_error = True
            continue

        for row in ticker_rows:
            existing = _get_existing_outcome(db_session, row.client_signal_id)
            if existing and existing.outcome in TERMINAL_OUTCOMES:
                _echo_skipped(row.client_signal_id)
                continue

            try:
                eval_result = evaluate_signal(
                    client_signal_id=row.client_signal_id,
                    ticker=row.ticker,
                    timeframe=row.timeframe,
                    entry_price=Decimal(row.price),
                    stop_loss=Decimal(row.stop_loss),
                    take_profit=Decimal(row.take_profit),
                    bar_time=row.bar_time,
                    risk_reward=Decimal(row.risk_reward) if row.risk_reward else None,
                    df=df,
                    lookahead_bars=resolved_lookahead,
                )
            except Exception as exc:
                click.echo(f"[{row.client_signal_id}] eval error: {exc}", err=True)
                has_error = True
                continue

            _echo_result(eval_result)

            if not dry_run:
                try:
                    _upsert(db_session, eval_result, row, existing)
                except Exception as exc:
                    click.echo(f"[{row.client_signal_id}] DB write failed: {exc}", err=True)
                    has_error = True

    db_session.close()
    sys.exit(1 if has_error else 0)


def _init_db(db_url: str) -> tuple:
    connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
    engine = create_engine(db_url, connect_args=connect_args)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def _query_signals(session, tickers: list[str], include_dry_run: bool) -> list[ForwardTestRun]:
    query = (
        session.query(ForwardTestRun)
        .filter(
            ForwardTestRun.client_signal_id.isnot(None),
            ForwardTestRun.price.isnot(None),
            ForwardTestRun.stop_loss.isnot(None),
            ForwardTestRun.take_profit.isnot(None),
            ForwardTestRun.bar_time.isnot(None),
            ForwardTestRun.status.in_(EVALUABLE_STATUSES),
            ForwardTestRun.ticker.in_(tickers),
        )
        .order_by(ForwardTestRun.created_at_utc.asc())
    )
    if not include_dry_run:
        query = query.filter(ForwardTestRun.is_dry_run == False)  # noqa: E712

    rows = query.all()

    # Deduplicate in Python: keep first occurrence per client_signal_id
    seen: set[str] = set()
    deduped: list[ForwardTestRun] = []
    for row in rows:
        if row.client_signal_id not in seen:
            seen.add(row.client_signal_id)
            deduped.append(row)
    return deduped


def _query_single_signal(session, client_signal_id: str, include_dry_run: bool) -> list[ForwardTestRun]:
    query = (
        session.query(ForwardTestRun)
        .filter(
            ForwardTestRun.client_signal_id == client_signal_id,
            ForwardTestRun.price.isnot(None),
            ForwardTestRun.stop_loss.isnot(None),
            ForwardTestRun.take_profit.isnot(None),
            ForwardTestRun.bar_time.isnot(None),
            ForwardTestRun.status.in_(EVALUABLE_STATUSES),
        )
        .order_by(ForwardTestRun.created_at_utc.asc())
    )
    if not include_dry_run:
        query = query.filter(ForwardTestRun.is_dry_run == False)  # noqa: E712

    row = query.first()
    return [row] if row is not None else []


def _get_existing_outcome(session, client_signal_id: str) -> Optional[SignalOutcome]:
    return session.query(SignalOutcome).filter_by(client_signal_id=client_signal_id).first()


def _is_terminal_in_db(session, client_signal_id: str) -> bool:
    existing = _get_existing_outcome(session, client_signal_id)
    return existing is not None and existing.outcome in TERMINAL_OUTCOMES


def _upsert(
    session,
    eval_result: EvaluationResult,
    source_row: ForwardTestRun,
    existing: Optional[SignalOutcome],
) -> None:
    if existing is None:
        row = SignalOutcome(
            client_signal_id=eval_result.client_signal_id,
            ticker=eval_result.ticker,
            timeframe=eval_result.timeframe,
            entry_price=source_row.price,
            stop_loss=source_row.stop_loss,
            take_profit=source_row.take_profit,
            bar_time=source_row.bar_time,
            forward_test_run_status=source_row.status,
            is_dry_run_source=source_row.is_dry_run,
            outcome=eval_result.outcome.value,
            outcome_bar_time_utc=eval_result.outcome_bar_time_utc,
            bars_to_outcome=eval_result.bars_to_outcome,
            pnl_r=eval_result.pnl_r,
            pnl_pct=eval_result.pnl_pct,
            max_favorable_excursion=eval_result.max_favorable_excursion,
            max_adverse_excursion=eval_result.max_adverse_excursion,
        )
        try:
            session.add(row)
            session.commit()
        except IntegrityError:
            session.rollback()
            raise
    elif existing.outcome == OutcomeStatus.PENDING.value:
        existing.outcome = eval_result.outcome.value
        existing.outcome_bar_time_utc = eval_result.outcome_bar_time_utc
        existing.bars_to_outcome = eval_result.bars_to_outcome
        existing.pnl_r = eval_result.pnl_r
        existing.pnl_pct = eval_result.pnl_pct
        existing.max_favorable_excursion = eval_result.max_favorable_excursion
        existing.max_adverse_excursion = eval_result.max_adverse_excursion
        existing.evaluated_at_utc = datetime.now(timezone.utc)
        session.commit()
    # Terminal outcome — do not modify


def _echo_result(eval_result: EvaluationResult) -> None:
    csid = eval_result.client_signal_id
    bars = eval_result.bars_to_outcome

    if eval_result.outcome == OutcomeStatus.TAKE_PROFIT_HIT:
        click.echo(f"[{csid}] take_profit_hit | pnl_r={eval_result.pnl_r} pnl_pct={eval_result.pnl_pct} bars={bars}")
    elif eval_result.outcome == OutcomeStatus.STOP_LOSS_HIT:
        click.echo(f"[{csid}] stop_loss_hit | pnl_r={eval_result.pnl_r} pnl_pct={eval_result.pnl_pct} bars={bars}")
    elif eval_result.outcome == OutcomeStatus.AMBIGUOUS_SAME_BAR:
        click.echo(f"[{csid}] ambiguous_same_bar | bars={bars}")
    elif eval_result.outcome == OutcomeStatus.TIMEOUT:
        click.echo(f"[{csid}] timeout | bars={bars}")
    elif eval_result.outcome == OutcomeStatus.PENDING:
        click.echo(f"[{csid}] pending | bars_available={bars}")


def _echo_skipped(client_signal_id: str) -> None:
    click.echo(f"[{client_signal_id}] skipped: terminal outcome already recorded")


def _parse_tickers(tickers_str: Optional[str]) -> Optional[list[str]]:
    if tickers_str is None:
        return None
    return [t.strip().upper() for t in tickers_str.split(",") if t.strip()]


if __name__ == "__main__":
    main()
