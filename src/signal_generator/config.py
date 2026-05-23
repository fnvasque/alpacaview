from decimal import Decimal
from typing import Any, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SignalGeneratorSettings(BaseSettings):
    PYTHON_SIGNAL_GENERATOR_ENABLED: bool = False
    SIGNAL_GENERATOR_BACKEND_URL: str = "http://127.0.0.1:8000"
    SIGNAL_GENERATOR_SECRET: Optional[str] = None
    WEBHOOK_SECRET: Optional[str] = None  # fallback if SIGNAL_GENERATOR_SECRET not set
    SIGNAL_GENERATOR_TICKERS: list[str] = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]
    SIGNAL_GENERATOR_TIMEFRAME: str = "15m"
    SIGNAL_GENERATOR_PERIOD: str = "5d"
    EMA_LENGTH: int = 21
    ATR_LENGTH: int = 14
    ATR_MULTIPLIER: Decimal = Decimal("1.5")
    RISK_REWARD: Decimal = Decimal("2.0")

    @model_validator(mode="after")
    def resolve_secret_with_fallback(self) -> "SignalGeneratorSettings":
        if not self.SIGNAL_GENERATOR_SECRET:
            if self.WEBHOOK_SECRET:
                object.__setattr__(self, "SIGNAL_GENERATOR_SECRET", self.WEBHOOK_SECRET)
            else:
                raise ValueError(
                    "SIGNAL_GENERATOR_SECRET is required. "
                    "Set SIGNAL_GENERATOR_SECRET in .env, or provide WEBHOOK_SECRET as a fallback."
                )
        return self

    @field_validator("SIGNAL_GENERATOR_TICKERS", mode="before")
    @classmethod
    def parse_signal_generator_tickers(cls, v: Any) -> list[str]:
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
