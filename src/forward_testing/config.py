from decimal import Decimal
from typing import Any, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ForwardTestingSettings(BaseSettings):
    FORWARD_TESTING_ENABLED: bool = False
    DATABASE_URL: Optional[str] = None
    FORWARD_TESTING_DB_URL: Optional[str] = None
    FORWARD_TESTING_BACKEND_URL: str = "http://127.0.0.1:8000"
    FORWARD_TESTING_SECRET: Optional[str] = None
    WEBHOOK_SECRET: Optional[str] = None
    FORWARD_TESTING_TICKERS: list[str] = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]
    FORWARD_TESTING_TIMEFRAME: str = "15m"
    FORWARD_TESTING_PERIOD: str = "5d"
    EMA_LENGTH: int = 21
    ATR_LENGTH: int = 14
    ATR_MULTIPLIER: Decimal = Decimal("1.5")
    RISK_REWARD: Decimal = Decimal("2.0")

    @model_validator(mode="after")
    def resolve_db_url(self) -> "ForwardTestingSettings":
        if not self.FORWARD_TESTING_DB_URL:
            object.__setattr__(
                self,
                "FORWARD_TESTING_DB_URL",
                self.DATABASE_URL or "sqlite:///./alpacaview.db",
            )
        return self

    @model_validator(mode="after")
    def resolve_secret(self) -> "ForwardTestingSettings":
        if not self.FORWARD_TESTING_SECRET:
            if self.WEBHOOK_SECRET:
                object.__setattr__(self, "FORWARD_TESTING_SECRET", self.WEBHOOK_SECRET)
            else:
                raise ValueError(
                    "FORWARD_TESTING_SECRET is required. "
                    "Set FORWARD_TESTING_SECRET in .env, or provide WEBHOOK_SECRET as a fallback."
                )
        return self

    @field_validator("FORWARD_TESTING_TICKERS", mode="before")
    @classmethod
    def parse_forward_testing_tickers(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [t.strip().upper() for t in v.split(",") if t.strip()]
        if isinstance(v, list):
            return [str(t).upper() for t in v if t]
        return []

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
