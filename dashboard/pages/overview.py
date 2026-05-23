import plotly.express as px
import streamlit as st

from src.reporting.db import get_reporting_session
from src.reporting.metrics import FilterParams, compute_global_metrics

engine = st.session_state["engine"]
filters: FilterParams = st.session_state.get("filters", FilterParams())

with get_reporting_session(engine) as session:
    metrics = compute_global_metrics(session, filters)

st.title("Overview")

win_rate_str = f"{metrics.win_rate:.1%}" if metrics.win_rate is not None else "—"
avg_r_str = f"{metrics.avg_r:.4f}" if metrics.avg_r is not None else "—"
total_r_str = f"{metrics.total_r:.4f}" if metrics.total_r is not None else "—"
avg_pnl_pct_str = f"{metrics.avg_pnl_pct:.2%}" if metrics.avg_pnl_pct is not None else "—"

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Signals", metrics.total_signals)
col2.metric("Evaluated Signals", metrics.evaluated_signals)
col3.metric("Pending Signals", metrics.pending_signals)
col4.metric("Win Rate", win_rate_str)

col5, col6, col7, col8 = st.columns(4)
col5.metric("Take Profit Hits", metrics.take_profit_hits)
col6.metric("Stop Loss Hits", metrics.stop_loss_hits)
col7.metric("Timeouts", metrics.timeouts)
col8.metric("Ambiguous", metrics.ambiguous_signals)

col9, col10, col11, _ = st.columns(4)
col9.metric("Avg R", avg_r_str)
col10.metric("Total R", total_r_str)
col11.metric("Avg PnL %", avg_pnl_pct_str)

outcome_labels = ["take_profit_hit", "stop_loss_hit", "ambiguous_same_bar", "timeout", "pending"]
outcome_counts = [
    metrics.take_profit_hits,
    metrics.stop_loss_hits,
    metrics.ambiguous_signals,
    metrics.timeouts,
    metrics.pending_signals,
]

fig = px.bar(
    x=outcome_labels,
    y=outcome_counts,
    labels={"x": "Outcome", "y": "Count"},
    title="Outcome Distribution",
    color=outcome_labels,
)
st.plotly_chart(fig, use_container_width=True)
