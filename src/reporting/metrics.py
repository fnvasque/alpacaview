from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Integer, func, distinct
from sqlalchemy.orm import Session

from app.models.forward_test_run import ForwardTestRun
from app.models.signal_outcome import SignalOutcome

EVALUABLE_STATUSES: tuple[str, ...] = (
    "signal_candidate",
    "risk_approved",
    "risk_rejected",
    "duplicate_signal",
)

TERMINAL_OUTCOMES: tuple[str, ...] = (
    "take_profit_hit",
    "stop_loss_hit",
    "ambiguous_same_bar",
    "timeout",
)


@dataclass
class FilterParams:
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    tickers: list[str] = field(default_factory=list)
    outcomes: list[str] = field(default_factory=list)
    include_dry_run: bool = False


@dataclass
class GlobalMetrics:
    total_signals: int = 0
    evaluated_signals: int = 0
    pending_signals: int = 0
    take_profit_hits: int = 0
    stop_loss_hits: int = 0
    timeouts: int = 0
    ambiguous_signals: int = 0
    win_rate: Optional[float] = None
    avg_r: Optional[float] = None
    total_r: Optional[float] = None
    avg_pnl_pct: Optional[float] = None


@dataclass
class TickerMetrics:
    ticker: str
    total_outcomes: int = 0
    take_profit_hit: int = 0
    stop_loss_hit: int = 0
    timeout: int = 0
    pending: int = 0
    win_rate: Optional[float] = None
    avg_r: Optional[float] = None
    total_r: Optional[float] = None


@dataclass
class BlockedSignalMetrics:
    total_rejected: int = 0
    by_reason_code: dict[str, int] = field(default_factory=dict)
    by_ticker: dict[str, int] = field(default_factory=dict)


@dataclass
class DailyMetrics:
    date: date
    signals_generated: int = 0
    signals_evaluated: int = 0
    take_profit_hit: int = 0
    stop_loss_hit: int = 0
    win_rate: Optional[float] = None
    avg_r: Optional[float] = None
    total_r: Optional[float] = None
    blocked_signals: int = 0


def _parse_float(value: Optional[str]) -> Optional[float]:
    return float(value) if value is not None else None


def _compute_win_rate(tp: int, sl: int) -> Optional[float]:
    denom = tp + sl
    return tp / denom if denom > 0 else None


def _apply_ftr_filters(query, filters: FilterParams):
    if filters.start_date:
        start_dt = datetime.combine(filters.start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        query = query.filter(ForwardTestRun.created_at_utc >= start_dt)
    if filters.end_date:
        end_dt = datetime.combine(filters.end_date + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc)
        query = query.filter(ForwardTestRun.created_at_utc < end_dt)
    if filters.tickers:
        query = query.filter(ForwardTestRun.ticker.in_(filters.tickers))
    if not filters.include_dry_run:
        query = query.filter(ForwardTestRun.is_dry_run == False)  # noqa: E712
    return query


def _apply_so_filters(query, filters: FilterParams):
    if filters.start_date:
        start_dt = datetime.combine(filters.start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        query = query.filter(SignalOutcome.created_at_utc >= start_dt)
    if filters.end_date:
        end_dt = datetime.combine(filters.end_date + timedelta(days=1), datetime.min.time()).replace(tzinfo=timezone.utc)
        query = query.filter(SignalOutcome.created_at_utc < end_dt)
    if filters.tickers:
        query = query.filter(SignalOutcome.ticker.in_(filters.tickers))
    if not filters.include_dry_run:
        query = query.filter(SignalOutcome.is_dry_run_source == False)  # noqa: E712
    if filters.outcomes:
        query = query.filter(SignalOutcome.outcome.in_(filters.outcomes))
    return query


def get_available_tickers(session: Session) -> list[str]:
    rows = (
        session.query(ForwardTestRun.ticker)
        .filter(ForwardTestRun.ticker.isnot(None))
        .distinct()
        .order_by(ForwardTestRun.ticker)
        .all()
    )
    return [row.ticker for row in rows]


def compute_global_metrics(session: Session, filters: FilterParams) -> GlobalMetrics:
    # Step 1 — total_signals from forward_test_runs
    base_q = session.query(func.count(distinct(ForwardTestRun.client_signal_id))).filter(
        ForwardTestRun.client_signal_id.isnot(None),
        ForwardTestRun.status.in_(EVALUABLE_STATUSES),
    )
    base_q = _apply_ftr_filters(base_q, filters)
    total_signals = base_q.scalar() or 0

    # Step 2 — outcome counts from signal_outcomes
    outcome_q = session.query(
        SignalOutcome.outcome,
        func.count(SignalOutcome.id),
    ).group_by(SignalOutcome.outcome)
    # Apply filters without the outcome filter (we want all outcomes for counting)
    filters_no_outcome = FilterParams(
        start_date=filters.start_date,
        end_date=filters.end_date,
        tickers=filters.tickers,
        outcomes=[],
        include_dry_run=filters.include_dry_run,
    )
    outcome_q = _apply_so_filters(outcome_q, filters_no_outcome)
    counts: dict[str, int] = {row[0]: row[1] for row in outcome_q.all()}

    evaluated_signals = sum(counts.get(o, 0) for o in TERMINAL_OUTCOMES)
    pending_signals = counts.get("pending", 0)
    take_profit_hits = counts.get("take_profit_hit", 0)
    stop_loss_hits = counts.get("stop_loss_hit", 0)
    timeouts = counts.get("timeout", 0)
    ambiguous_signals = counts.get("ambiguous_same_bar", 0)

    # Step 3 — pnl_r aggregation
    pnl_r_q = session.query(SignalOutcome.pnl_r).filter(SignalOutcome.pnl_r.isnot(None))
    pnl_r_q = _apply_so_filters(pnl_r_q, filters)
    pnl_r_values = [_parse_float(row.pnl_r) for row in pnl_r_q.all() if row.pnl_r is not None]
    total_r = sum(pnl_r_values) if pnl_r_values else None
    avg_r = total_r / len(pnl_r_values) if pnl_r_values else None

    # Step 4 — pnl_pct aggregation
    pnl_pct_q = session.query(SignalOutcome.pnl_pct).filter(SignalOutcome.pnl_pct.isnot(None))
    pnl_pct_q = _apply_so_filters(pnl_pct_q, filters)
    pnl_pct_values = [_parse_float(row.pnl_pct) for row in pnl_pct_q.all() if row.pnl_pct is not None]
    avg_pnl_pct = sum(pnl_pct_values) / len(pnl_pct_values) if pnl_pct_values else None

    return GlobalMetrics(
        total_signals=total_signals,
        evaluated_signals=evaluated_signals,
        pending_signals=pending_signals,
        take_profit_hits=take_profit_hits,
        stop_loss_hits=stop_loss_hits,
        timeouts=timeouts,
        ambiguous_signals=ambiguous_signals,
        win_rate=_compute_win_rate(take_profit_hits, stop_loss_hits),
        avg_r=avg_r,
        total_r=total_r,
        avg_pnl_pct=avg_pnl_pct,
    )


def compute_ticker_metrics(session: Session, filters: FilterParams) -> list[TickerMetrics]:
    # Step 1 — outcome counts grouped by ticker and outcome
    count_q = session.query(
        SignalOutcome.ticker,
        SignalOutcome.outcome,
        func.count(SignalOutcome.id),
    ).group_by(SignalOutcome.ticker, SignalOutcome.outcome)
    count_q = _apply_so_filters(count_q, filters)

    by_ticker: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for ticker, outcome, cnt in count_q.all():
        by_ticker[ticker][outcome] = cnt

    # Step 2 — pnl_r values grouped by ticker
    pnl_q = session.query(SignalOutcome.ticker, SignalOutcome.pnl_r).filter(
        SignalOutcome.pnl_r.isnot(None)
    )
    pnl_q = _apply_so_filters(pnl_q, filters)

    pnl_by_ticker: dict[str, list[float]] = defaultdict(list)
    for ticker, pnl_r in pnl_q.all():
        if pnl_r is not None:
            pnl_by_ticker[ticker].append(float(pnl_r))

    # Step 3 — build TickerMetrics list
    result = []
    for ticker in sorted(by_ticker.keys()):
        outcome_counts = by_ticker[ticker]
        tp = outcome_counts.get("take_profit_hit", 0)
        sl = outcome_counts.get("stop_loss_hit", 0)
        timeout = outcome_counts.get("timeout", 0)
        pending = outcome_counts.get("pending", 0)
        total_outcomes = sum(outcome_counts.values())

        pnl_vals = pnl_by_ticker.get(ticker, [])
        total_r = sum(pnl_vals) if pnl_vals else None
        avg_r = total_r / len(pnl_vals) if pnl_vals else None

        result.append(TickerMetrics(
            ticker=ticker,
            total_outcomes=total_outcomes,
            take_profit_hit=tp,
            stop_loss_hit=sl,
            timeout=timeout,
            pending=pending,
            win_rate=_compute_win_rate(tp, sl),
            avg_r=avg_r,
            total_r=total_r,
        ))
    return result


def compute_blocked_signals(session: Session, filters: FilterParams) -> BlockedSignalMetrics:
    # Step 1 — total_rejected
    total_q = session.query(func.count(ForwardTestRun.id)).filter(
        ForwardTestRun.status == "risk_rejected"
    )
    total_q = _apply_ftr_filters(total_q, filters)
    total_rejected = total_q.scalar() or 0

    # Step 2 — by_reason_code
    reason_q = (
        session.query(ForwardTestRun.backend_reason_code, func.count(ForwardTestRun.id))
        .filter(ForwardTestRun.status == "risk_rejected")
        .group_by(ForwardTestRun.backend_reason_code)
    )
    reason_q = _apply_ftr_filters(reason_q, filters)
    by_reason_code: dict[str, int] = {}
    for reason_code, cnt in reason_q.all():
        key = reason_code if reason_code is not None else "unknown"
        by_reason_code[key] = by_reason_code.get(key, 0) + cnt

    # Step 3 — by_ticker
    ticker_q = (
        session.query(ForwardTestRun.ticker, func.count(ForwardTestRun.id))
        .filter(ForwardTestRun.status == "risk_rejected")
        .group_by(ForwardTestRun.ticker)
    )
    ticker_q = _apply_ftr_filters(ticker_q, filters)
    by_ticker: dict[str, int] = {ticker: cnt for ticker, cnt in ticker_q.all()}

    return BlockedSignalMetrics(
        total_rejected=total_rejected,
        by_reason_code=by_reason_code,
        by_ticker=by_ticker,
    )


def compute_daily_evolution(session: Session, filters: FilterParams) -> list[DailyMetrics]:
    # Step 1 — signals_generated and blocked_signals per date from forward_test_runs
    _ftr_date = func.date(ForwardTestRun.created_at_utc)
    ftr_q = (
        session.query(
            _ftr_date.label("d"),
            func.count(distinct(ForwardTestRun.client_signal_id)).label("generated"),
            func.sum(
                (ForwardTestRun.status == "risk_rejected").cast(Integer)
            ).label("blocked"),
        )
        .filter(
            ForwardTestRun.client_signal_id.isnot(None),
            ForwardTestRun.status.in_(EVALUABLE_STATUSES),
        )
        .group_by(_ftr_date)
    )
    ftr_q = _apply_ftr_filters(ftr_q, filters)
    ftr_by_date: dict[str, tuple[int, int]] = {}
    for row in ftr_q.all():
        ftr_by_date[str(row.d)] = (row.generated or 0, row.blocked or 0)

    # Step 2a — outcome counts per date from signal_outcomes
    _so_date = func.date(SignalOutcome.created_at_utc)
    so_count_q = (
        session.query(
            _so_date.label("d"),
            SignalOutcome.outcome,
            func.count(SignalOutcome.id).label("cnt"),
        )
        .group_by(_so_date, SignalOutcome.outcome)
    )
    filters_no_outcome = FilterParams(
        start_date=filters.start_date,
        end_date=filters.end_date,
        tickers=filters.tickers,
        outcomes=[],
        include_dry_run=filters.include_dry_run,
    )
    so_count_q = _apply_so_filters(so_count_q, filters_no_outcome)
    so_by_date: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in so_count_q.all():
        so_by_date[str(row.d)][row.outcome] = row.cnt

    # Step 2b — pnl_r per date from signal_outcomes
    pnl_q = session.query(
        func.date(SignalOutcome.created_at_utc).label("d"),
        SignalOutcome.pnl_r,
    ).filter(SignalOutcome.pnl_r.isnot(None))
    pnl_q = _apply_so_filters(pnl_q, filters_no_outcome)
    pnl_by_date: dict[str, list[float]] = defaultdict(list)
    for row in pnl_q.all():
        if row.pnl_r is not None:
            pnl_by_date[str(row.d)].append(float(row.pnl_r))

    # Step 3 — merge all dates and build DailyMetrics list
    all_dates = sorted(set(list(ftr_by_date.keys()) + list(so_by_date.keys())))
    result = []
    for d_str in all_dates:
        generated, blocked = ftr_by_date.get(d_str, (0, 0))
        outcome_counts = so_by_date.get(d_str, {})
        tp = outcome_counts.get("take_profit_hit", 0)
        sl = outcome_counts.get("stop_loss_hit", 0)
        signals_evaluated = sum(outcome_counts.get(o, 0) for o in TERMINAL_OUTCOMES)

        pnl_vals = pnl_by_date.get(d_str, [])
        total_r = sum(pnl_vals) if pnl_vals else None
        avg_r = total_r / len(pnl_vals) if pnl_vals else None

        try:
            parsed_date = date.fromisoformat(d_str)
        except (ValueError, TypeError):
            continue

        result.append(DailyMetrics(
            date=parsed_date,
            signals_generated=generated,
            signals_evaluated=signals_evaluated,
            take_profit_hit=tp,
            stop_loss_hit=sl,
            win_rate=_compute_win_rate(tp, sl),
            avg_r=avg_r,
            total_r=total_r,
            blocked_signals=blocked,
        ))
    return result
