import pandas as pd
import plotly.express as px
import streamlit as st

from src.reporting.db import get_reporting_session
from src.reporting.metrics import FilterParams, compute_daily_evolution

engine = st.session_state["engine"]
filters: FilterParams = st.session_state.get("filters", FilterParams())

with get_reporting_session(engine) as session:
    daily_list = compute_daily_evolution(session, filters)

st.title("Daily Evolution")

if not daily_list:
    st.info("No daily data found for the selected filters.")
else:
    rows = [
        {
            "date": m.date,
            "signals_generated": m.signals_generated,
            "signals_evaluated": m.signals_evaluated,
            "take_profit_hit": m.take_profit_hit,
            "stop_loss_hit": m.stop_loss_hit,
            "win_rate": m.win_rate,
            "avg_r": m.avg_r,
            "total_r": m.total_r,
            "blocked_signals": m.blocked_signals,
        }
        for m in daily_list
    ]
    df = pd.DataFrame(rows)

    fig_volume = px.line(
        df,
        x="date",
        y=["signals_generated", "signals_evaluated", "blocked_signals"],
        labels={"value": "Count", "variable": "Metric"},
        title="Signal Volume Over Time",
    )
    st.plotly_chart(fig_volume, use_container_width=True)

    fig_outcomes = px.line(
        df,
        x="date",
        y=["take_profit_hit", "stop_loss_hit"],
        labels={"value": "Count", "variable": "Outcome"},
        title="TP vs SL Over Time",
    )
    st.plotly_chart(fig_outcomes, use_container_width=True)

    wr_df = df[df["win_rate"].notna()].copy()
    if not wr_df.empty:
        fig_wr = px.line(
            wr_df,
            x="date",
            y="win_rate",
            labels={"win_rate": "Win Rate"},
            title="Win Rate Over Time",
        )
        st.plotly_chart(fig_wr, use_container_width=True)

    avg_r_df = df[df["avg_r"].notna()].copy()
    if not avg_r_df.empty:
        fig_avgr = px.line(
            avg_r_df,
            x="date",
            y="avg_r",
            labels={"avg_r": "Avg R"},
            title="Avg R Over Time",
        )
        st.plotly_chart(fig_avgr, use_container_width=True)

    st.dataframe(df, use_container_width=True)
