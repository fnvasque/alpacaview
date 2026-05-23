import pandas as pd
import plotly.express as px
import streamlit as st

from src.reporting.db import get_reporting_session
from src.reporting.metrics import FilterParams, compute_ticker_metrics

engine = st.session_state["engine"]
filters: FilterParams = st.session_state.get("filters", FilterParams())

with get_reporting_session(engine) as session:
    metrics_list = compute_ticker_metrics(session, filters)

st.title("Outcomes by Ticker")

if not metrics_list:
    st.info("No outcome data found for the selected filters.")
else:
    rows = [
        {
            "ticker": m.ticker,
            "total_outcomes": m.total_outcomes,
            "take_profit_hit": m.take_profit_hit,
            "stop_loss_hit": m.stop_loss_hit,
            "timeout": m.timeout,
            "pending": m.pending,
            "win_rate": m.win_rate,
            "avg_r": m.avg_r,
            "total_r": m.total_r,
        }
        for m in metrics_list
    ]
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)

    fig_breakdown = px.bar(
        df,
        x="ticker",
        y=["take_profit_hit", "stop_loss_hit", "timeout", "pending"],
        barmode="group",
        labels={"value": "Count", "variable": "Outcome"},
        title="Outcome Breakdown by Ticker",
    )
    st.plotly_chart(fig_breakdown, use_container_width=True)

    wr_df = df[df["win_rate"].notna()].copy()
    if not wr_df.empty:
        fig_wr = px.bar(
            wr_df,
            x="ticker",
            y="win_rate",
            labels={"win_rate": "Win Rate"},
            title="Win Rate by Ticker",
        )
        st.plotly_chart(fig_wr, use_container_width=True)
