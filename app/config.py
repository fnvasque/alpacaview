from decimal import Decimal
from functools import lru_cache
from typing import Any, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    WEBHOOK_SECRET: str
    DATABASE_URL: str = "sqlite:///./alpacaview.db"
    INITIAL_EQUITY: Decimal = Decimal("10000")
    DAILY_TARGET_PCT: Decimal = Decimal("0.003")
    # Reserved for V1/V2. Has no effect in V0. Risk Engine does not read this.
    STOP_AFTER_DAILY_TARGET: bool = False
    KILL_SWITCH: bool = False
    MAX_DAILY_TRADES: int = 3
    MAX_DAILY_LOSS_PCT: Decimal = Decimal("0.0075")
    MAX_WEEKLY_LOSS_PCT: Decimal = Decimal("0.025")
    MAX_CONSECUTIVE_LOSSES: int = 2
    # Comma-separated uppercase tickers. Empty list = allow all non-crypto.
    ALLOWED_TICKERS: list[str] = []
    MIN_RISK_REWARD: Decimal = Decimal("1.5")
    # Comma-separated timeframes. Empty list = allow all.
    ALLOWED_TIMEFRAMES: list[str] = ["5m", "15m", "1h"]
    # 0 = disabled.
    MAX_SIGNAL_AGE_SECONDS: int = 900
    LOG_LEVEL: str = "INFO"
    RESEND_RECEIVING_ENABLED: bool = False
    RESEND_API_KEY: Optional[str] = None
    RESEND_WEBHOOK_SECRET: Optional[str] = None
    RESEND_MAX_EMAIL_BODY_CHARS: int = 50000

    @field_validator("ALLOWED_TICKERS", mode="before")
    @classmethod
    def parse_allowed_tickers(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [t.strip().upper() for t in v.split(",") if t.strip()]
        if isinstance(v, list):
            return [str(t).upper() for t in v if t]
        return []

    @field_validator("ALLOWED_TIMEFRAMES", mode="before")
    @classmethod
    def parse_allowed_timeframes(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        if isinstance(v, list):
            return [str(t) for t in v if t]
        return []

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
