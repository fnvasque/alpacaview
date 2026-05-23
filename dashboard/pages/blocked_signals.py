import pandas as pd
import plotly.express as px
import streamlit as st

from src.reporting.db import get_reporting_session
from src.reporting.metrics import FilterParams, compute_blocked_signals

engine = st.session_state["engine"]
filters: FilterParams = st.session_state.get("filters", FilterParams())

with get_reporting_session(engine) as session:
    metrics = compute_blocked_signals(session, filters)

st.title("Blocked Signals")
st.metric("Total Blocked", metrics.total_rejected)

if metrics.by_reason_code:
    reason_df = pd.DataFrame(
        list(metrics.by_reason_code.items()),
        columns=["reason_code", "count"],
    ).sort_values("count", ascending=False)

    fig_reason = px.bar(
        reason_df,
        x="reason_code",
        y="count",
        labels={"reason_code": "Reason Code", "count": "Count"},
        title="Blocked Signals by Reason Code",
    )
    st.plotly_chart(fig_reason, use_container_width=True)
    st.dataframe(reason_df, use_container_width=True)
else:
    st.info("No blocked signals found.")

if metrics.by_ticker:
    ticker_df = pd.DataFrame(
        list(metrics.by_ticker.items()),
        columns=["ticker", "count"],
    ).sort_values("count", ascending=False)

    fig_ticker = px.bar(
        ticker_df,
        x="ticker",
        y="count",
        labels={"ticker": "Ticker", "count": "Count"},
        title="Blocked Signals by Ticker",
    )
    st.plotly_chart(fig_ticker, use_container_width=True)
    st.dataframe(ticker_df, use_container_width=True)
