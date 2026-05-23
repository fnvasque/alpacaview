from pathlib import Path
import sys

import streamlit as st


# -----------------------------------------------------------------------------
# Robust project path setup
# -----------------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
PAGES_DIR = CURRENT_DIR / "pages"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# -----------------------------------------------------------------------------
# Imports that depend on project root being available
# -----------------------------------------------------------------------------
from src.reporting.config import DashboardSettings  # noqa: E402
from src.reporting.db import get_reporting_engine  # noqa: E402


# -----------------------------------------------------------------------------
# Streamlit config
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="AlpacaView Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# -----------------------------------------------------------------------------
# Cached resources
# -----------------------------------------------------------------------------
@st.cache_resource
def load_dashboard_settings() -> DashboardSettings:
    return DashboardSettings()


@st.cache_resource
def load_reporting_engine():
    settings = load_dashboard_settings()

    try:
        return get_reporting_engine(settings.DASHBOARD_DB_URL)
    except TypeError:
        return get_reporting_engine()


settings = load_dashboard_settings()
engine = load_reporting_engine()


# -----------------------------------------------------------------------------
# Session state expected by dashboard pages
# -----------------------------------------------------------------------------
st.session_state["settings"] = settings
st.session_state["dashboard_settings"] = settings

st.session_state["engine"] = engine
st.session_state["reporting_engine"] = engine


# -----------------------------------------------------------------------------
# Sidebar
# -----------------------------------------------------------------------------
st.sidebar.title("AlpacaView")
st.sidebar.caption("Forward Testing Dashboard")

st.sidebar.divider()

st.sidebar.markdown("### Database")
st.sidebar.code(settings.DASHBOARD_DB_URL, language="text")

st.sidebar.divider()

st.sidebar.markdown("### Filters")

st.session_state.setdefault("selected_tickers", [])
st.session_state.setdefault("selected_outcomes", [])
st.session_state.setdefault("selected_statuses", [])
st.session_state.setdefault("date_range", None)

st.sidebar.caption(
    "Use each page's filters/tables to explore signals, outcomes, blocked trades and daily evolution."
)

st.sidebar.divider()

if st.sidebar.button("Clear cache / refresh data"):
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()


# -----------------------------------------------------------------------------
# Page paths
# -----------------------------------------------------------------------------
overview_page = PAGES_DIR / "overview.py"
outcomes_by_ticker_page = PAGES_DIR / "outcomes_by_ticker.py"
blocked_signals_page = PAGES_DIR / "blocked_signals.py"
daily_evolution_page = PAGES_DIR / "daily_evolution.py"
raw_data_page = PAGES_DIR / "raw_data.py"

required_pages = [
    overview_page,
    outcomes_by_ticker_page,
    blocked_signals_page,
    daily_evolution_page,
    raw_data_page,
]

missing_pages = [page for page in required_pages if not page.exists()]

if missing_pages:
    st.error("Some dashboard pages are missing.")
    for page in missing_pages:
        st.code(str(page), language="text")
    st.stop()


# -----------------------------------------------------------------------------
# Navigation
# -----------------------------------------------------------------------------
pages = [
    st.Page(str(overview_page), title="Overview", icon="📊"),
    st.Page(str(outcomes_by_ticker_page), title="Outcomes by Ticker", icon="🎯"),
    st.Page(str(blocked_signals_page), title="Blocked Signals", icon="🛑"),
    st.Page(str(daily_evolution_page), title="Daily Evolution", icon="📈"),
    st.Page(str(raw_data_page), title="Raw Data", icon="🧾"),
]

navigation = st.navigation(pages)
navigation.run()