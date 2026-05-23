import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Must be set before any Settings() instantiation (main.py calls get_settings() in create_app).
os.environ.setdefault("WEBHOOK_SECRET", "test-secret")

# Import all models so Base.metadata knows about them before create_all().
import app.models.signal  # noqa: F401
import app.models.decision  # noqa: F401
import app.models.webhook_event  # noqa: F401
import app.models.kill_switch  # noqa: F401

from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        WEBHOOK_SECRET="test-secret",
        DATABASE_URL="sqlite://",
        INITIAL_EQUITY=Decimal("10000"),
        STOP_AFTER_DAILY_TARGET=False,
        KILL_SWITCH=False,
        ALLOWED_TICKERS=["SPY", "QQQ", "AAPL", "MSFT", "NVDA"],
        MAX_DAILY_TRADES=3,
        MAX_DAILY_LOSS_PCT=Decimal("0.0075"),
        MAX_WEEKLY_LOSS_PCT=Decimal("0.025"),
        MAX_CONSECUTIVE_LOSSES=2,
        DAILY_TARGET_PCT=Decimal("0.003"),
        MIN_RISK_REWARD=Decimal("1.5"),
        ALLOWED_TIMEFRAMES=["5m", "15m", "1h"],
        MAX_SIGNAL_AGE_SECONDS=900,
        # Pin Resend to disabled so tests are isolated from .env
        RESEND_RECEIVING_ENABLED=False,
        RESEND_API_KEY=None,
        RESEND_WEBHOOK_SECRET=None,
        RESEND_MAX_EMAIL_BODY_CHARS=50000,
    )


@pytest.fixture
def db(settings: Settings):
    # StaticPool: every connect() call returns the same underlying connection,
    # so tables created by create_all() are visible to all sessions including
    # the ones created inside the TestClient request handlers.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db: Session, settings: Settings) -> TestClient:
    application = create_app()

    def override_get_db():
        yield db

    def override_get_settings():
        return settings

    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[get_settings] = override_get_settings

    with TestClient(application) as test_client:
        yield test_client

    application.dependency_overrides.clear()


@pytest.fixture
def valid_payload() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "secret": "test-secret",
        "client_signal_id": str(uuid4()),
        "strategy": "momentum_pullback",
        "version": "1.0",
        "ticker": "SPY",
        "side": "buy",
        "price": "450.00",
        "stop_loss": "445.00",
        "take_profit": "458.00",
        "timeframe": "5m",
        "bar_time": (now - timedelta(minutes=5)).isoformat(),
        "event_time": now.isoformat(),
    }


@pytest.fixture
def make_payload(valid_payload: dict):
    def _make(**overrides) -> dict:
        return {**valid_payload, **overrides}

    return _make
