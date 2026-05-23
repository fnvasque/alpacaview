import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session

from app.models.forward_test_run import ForwardTestRun
from app.models.signal_outcome import SignalOutcome
from src.reporting.db import get_reporting_session
from src.reporting.metrics import FilterParams, _apply_ftr_filters, _apply_so_filters

engine = st.session_state["engine"]
filters: FilterParams = st.session_state.get("filters", FilterParams())

st.title("Raw Data")

tab1, tab2 = st.tabs(["forward_test_runs", "signal_outcomes"])

with tab1:
    with get_reporting_session(engine) as session:
        q = session.query(ForwardTestRun)
        q = _apply_ftr_filters(q, filters)
        rows = q.order_by(ForwardTestRun.created_at_utc.desc()).limit(1000).all()

    if rows:
        ftr_data = [
            {
                "id": r.id,
                "run_id": r.run_id,
                "ticker": r.ticker,
                "timeframe": r.timeframe,
                "period": r.period,
                "status": r.status,
                "is_dry_run": r.is_dry_run,
                "client_signal_id": r.client_signal_id,
                "price": r.price,
                "stop_loss": r.stop_loss,
                "take_profit": r.take_profit,
                "risk_reward": r.risk_reward,
                "backend_approved": r.backend_approved,
                "backend_reason_code": r.backend_reason_code,
                "backend_reason_detail": r.backend_reason_detail,
                "created_at_utc": r.created_at_utc,
            }
            for r in rows
        ]
        ftr_df = pd.DataFrame(ftr_data)
        st.dataframe(ftr_df, use_container_width=True)
        st.download_button(
            "Download CSV",
            data=ftr_df.to_csv(index=False).encode("utf-8"),
            file_name="forward_test_runs.csv",
            mime="text/csv",
        )
    else:
        st.info("No forward_test_runs data found for the selected filters.")

with tab2:
    with get_reporting_session(engine) as session:
        q = session.query(SignalOutcome)
        q = _apply_so_filters(q, filters)
        rows = q.order_by(SignalOutcome.created_at_utc.desc()).limit(1000).all()

    if rows:
        so_data = [
            {
                "id": r.id,
                "client_signal_id": r.client_signal_id,
                "ticker": r.ticker,
                "timeframe": r.timeframe,
                "outcome": r.outcome,
                "bars_to_outcome": r.bars_to_outcome,
                "pnl_r": float(r.pnl_r) if r.pnl_r is not None else None,
                "pnl_pct": float(r.pnl_pct) if r.pnl_pct is not None else None,
                "max_favorable_excursion": float(r.max_favorable_excursion) if r.max_favorable_excursion is not None else None,
                "max_adverse_excursion": float(r.max_adverse_excursion) if r.max_adverse_excursion is not None else None,
                "outcome_bar_time_utc": r.outcome_bar_time_utc,
                "is_dry_run_source": r.is_dry_run_source,
                "evaluated_at_utc": r.evaluated_at_utc,
                "created_at_utc": r.created_at_utc,
            }
            for r in rows
        ]
        so_df = pd.DataFrame(so_data)
        st.dataframe(so_df, use_container_width=True)
        st.download_button(
            "Download CSV",
            data=so_df.to_csv(index=False).encode("utf-8"),
            file_name="signal_outcomes.csv",
            mime="text/csv",
            key="so_download",
        )
    else:
        st.info("No signal_outcomes data found for the selected filters.")
