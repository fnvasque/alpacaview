"""
Unit tests for SignalGeneratorSettings.

All tests use constructor kwargs (highest priority in pydantic-settings) so
they are isolated from the project's actual .env file and OS environment.
"""
import pytest
from pydantic import ValidationError

from src.signal_generator.config import SignalGeneratorSettings


# ── extra="ignore" ─────────────────────────────────────────────────────────────

def test_ignores_server_env_fields() -> None:
    # Server-only fields like DATABASE_URL or KILL_SWITCH must not raise.
    settings = SignalGeneratorSettings(
        SIGNAL_GENERATOR_SECRET="test-secret",
        DATABASE_URL="sqlite:///test.db",
        KILL_SWITCH="false",
        MAX_DAILY_TRADES="3",
        _env_file=None,
    )
    assert settings.SIGNAL_GENERATOR_SECRET == "test-secret"


def test_ignores_resend_fields() -> None:
    settings = SignalGeneratorSettings(
        SIGNAL_GENERATOR_SECRET="test-secret",
        RESEND_API_KEY="re_xxxxx",
        RESEND_RECEIVING_ENABLED="true",
        _env_file=None,
    )
    assert settings.SIGNAL_GENERATOR_SECRET == "test-secret"


# ── SIGNAL_GENERATOR_SECRET ────────────────────────────────────────────────────

def test_loads_signal_generator_secret() -> None:
    settings = SignalGeneratorSettings(
        SIGNAL_GENERATOR_SECRET="direct-secret",
        _env_file=None,
    )
    assert settings.SIGNAL_GENERATOR_SECRET == "direct-secret"


def test_signal_generator_secret_takes_priority_over_webhook_secret() -> None:
    settings = SignalGeneratorSettings(
        SIGNAL_GENERATOR_SECRET="generator-secret",
        WEBHOOK_SECRET="server-secret",
        _env_file=None,
    )
    assert settings.SIGNAL_GENERATOR_SECRET == "generator-secret"


# ── WEBHOOK_SECRET fallback ────────────────────────────────────────────────────

def test_fallback_to_webhook_secret_when_generator_secret_absent() -> None:
    settings = SignalGeneratorSettings(
        WEBHOOK_SECRET="fallback-secret",
        _env_file=None,
    )
    assert settings.SIGNAL_GENERATOR_SECRET == "fallback-secret"


def test_fallback_to_webhook_secret_when_generator_secret_is_none() -> None:
    settings = SignalGeneratorSettings(
        SIGNAL_GENERATOR_SECRET=None,
        WEBHOOK_SECRET="webhook-fallback",
        _env_file=None,
    )
    assert settings.SIGNAL_GENERATOR_SECRET == "webhook-fallback"


def test_missing_both_secrets_raises_validation_error() -> None:
    with pytest.raises(ValidationError, match="SIGNAL_GENERATOR_SECRET is required"):
        SignalGeneratorSettings(
            SIGNAL_GENERATOR_SECRET=None,
            WEBHOOK_SECRET=None,
            _env_file=None,
        )


# ── Defaults ───────────────────────────────────────────────────────────────────

def test_default_values() -> None:
    settings = SignalGeneratorSettings(
        SIGNAL_GENERATOR_SECRET="s",
        _env_file=None,
    )
    assert settings.PYTHON_SIGNAL_GENERATOR_ENABLED is False
    assert settings.SIGNAL_GENERATOR_BACKEND_URL == "http://127.0.0.1:8000"
    assert settings.SIGNAL_GENERATOR_TICKERS == ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]
    assert settings.SIGNAL_GENERATOR_TIMEFRAME == "15m"
    assert settings.SIGNAL_GENERATOR_PERIOD == "5d"
    assert settings.EMA_LENGTH == 21
    assert settings.ATR_LENGTH == 14


def test_tickers_parsed_from_comma_string() -> None:
    settings = SignalGeneratorSettings(
        SIGNAL_GENERATOR_SECRET="s",
        SIGNAL_GENERATOR_TICKERS="spy, qqq, aapl",
        _env_file=None,
    )
    assert settings.SIGNAL_GENERATOR_TICKERS == ["SPY", "QQQ", "AAPL"]
