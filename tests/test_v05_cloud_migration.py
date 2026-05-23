import pathlib

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.forward_testing.config import ForwardTestingSettings
from src.outcome_evaluator.config import OutcomeEvaluatorSettings
from src.reporting.config import DashboardSettings

POSTGRES_URL = "postgresql://user:pass@host:5432/db"
SQLITE_DEFAULT = "sqlite:///./alpacaview.db"


def _make_isolated(base_cls, **init_kwargs):
    class _Isolated(base_cls):
        model_config = SettingsConfigDict(env_file=None, extra="ignore")

    return _Isolated(**init_kwargs)


def _scan_files(*glob_dirs: str, pattern: str) -> list[str]:
    matches = []
    root = pathlib.Path(".")
    for d in glob_dirs:
        for f in root.glob(f"{d}/**/*.py"):
            if pattern in f.read_text():
                matches.append(str(f))
    return matches


# ---------------------------------------------------------------------------
# ForwardTestingSettings — DATABASE_URL fallback
# ---------------------------------------------------------------------------


def test_forward_testing_uses_database_url_when_specific_url_not_set():
    settings = _make_isolated(
        ForwardTestingSettings,
        DATABASE_URL=POSTGRES_URL,
        WEBHOOK_SECRET="secret",
    )
    assert settings.FORWARD_TESTING_DB_URL == POSTGRES_URL


def test_forward_testing_specific_url_takes_precedence():
    specific = "sqlite:///./other.db"
    settings = _make_isolated(
        ForwardTestingSettings,
        DATABASE_URL=POSTGRES_URL,
        FORWARD_TESTING_DB_URL=specific,
        WEBHOOK_SECRET="secret",
    )
    assert settings.FORWARD_TESTING_DB_URL == specific


def test_forward_testing_defaults_to_sqlite_when_neither_set():
    settings = _make_isolated(ForwardTestingSettings, WEBHOOK_SECRET="secret")
    assert settings.FORWARD_TESTING_DB_URL == SQLITE_DEFAULT


# ---------------------------------------------------------------------------
# OutcomeEvaluatorSettings — DATABASE_URL fallback
# ---------------------------------------------------------------------------


def test_outcome_evaluator_uses_database_url_when_specific_url_not_set():
    settings = _make_isolated(OutcomeEvaluatorSettings, DATABASE_URL=POSTGRES_URL)
    assert settings.OUTCOME_EVALUATOR_DB_URL == POSTGRES_URL


def test_outcome_evaluator_specific_url_takes_precedence():
    specific = "sqlite:///./other.db"
    settings = _make_isolated(
        OutcomeEvaluatorSettings,
        DATABASE_URL=POSTGRES_URL,
        OUTCOME_EVALUATOR_DB_URL=specific,
    )
    assert settings.OUTCOME_EVALUATOR_DB_URL == specific


def test_outcome_evaluator_defaults_to_sqlite():
    settings = _make_isolated(OutcomeEvaluatorSettings)
    assert settings.OUTCOME_EVALUATOR_DB_URL == SQLITE_DEFAULT


# ---------------------------------------------------------------------------
# DashboardSettings — DATABASE_URL fallback
# ---------------------------------------------------------------------------


def test_dashboard_uses_database_url_when_specific_url_not_set():
    settings = _make_isolated(DashboardSettings, DATABASE_URL=POSTGRES_URL)
    assert settings.DASHBOARD_DB_URL == POSTGRES_URL


def test_dashboard_specific_url_takes_precedence():
    specific = "sqlite:///./other.db"
    settings = _make_isolated(
        DashboardSettings,
        DATABASE_URL=POSTGRES_URL,
        DASHBOARD_DB_URL=specific,
    )
    assert settings.DASHBOARD_DB_URL == specific


def test_dashboard_defaults_to_sqlite():
    settings = _make_isolated(DashboardSettings)
    assert settings.DASHBOARD_DB_URL == SQLITE_DEFAULT


# ---------------------------------------------------------------------------
# Safety scans — no Alpaca, no order execution
# ---------------------------------------------------------------------------


def test_no_alpaca_imports_in_src():
    matches = _scan_files("src", pattern="import alpaca") + _scan_files("src", pattern="from alpaca")
    assert matches == [], f"Alpaca SDK imports found in src/: {matches}"


def test_no_alpaca_imports_in_app():
    matches = _scan_files("app", pattern="import alpaca") + _scan_files("app", pattern="from alpaca")
    assert matches == [], f"Alpaca SDK imports found in app/: {matches}"


def test_no_alpaca_imports_in_dashboard():
    matches = _scan_files("dashboard", pattern="import alpaca") + _scan_files("dashboard", pattern="from alpaca")
    assert matches == [], f"Alpaca SDK imports found in dashboard/: {matches}"


def test_no_order_execution_in_source():
    forbidden = ["place_order", "submit_order", "create_order", "alpaca_trade_api", "alpaca.trading"]
    for pattern in forbidden:
        matches = _scan_files("src", "app", pattern=pattern)
        assert matches == [], f"Forbidden pattern '{pattern}' found in: {matches}"
