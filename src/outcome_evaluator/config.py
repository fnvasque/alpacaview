from typing import Any, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OutcomeEvaluatorSettings(BaseSettings):
    OUTCOME_EVALUATOR_ENABLED: bool = False
    DATABASE_URL: Optional[str] = None
    OUTCOME_EVALUATOR_DB_URL: Optional[str] = None
    OUTCOME_EVALUATOR_TICKERS: list[str] = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]
    OUTCOME_EVALUATOR_TIMEFRAME: str = "15m"
    OUTCOME_EVALUATOR_PERIOD: str = "5d"
    OUTCOME_LOOKAHEAD_BARS: int = 26

    @model_validator(mode="after")
    def resolve_db_url(self) -> "OutcomeEvaluatorSettings":
        if not self.OUTCOME_EVALUATOR_DB_URL:
            object.__setattr__(
                self,
                "OUTCOME_EVALUATOR_DB_URL",
                self.DATABASE_URL or "sqlite:///./alpacaview.db",
            )
        return self

    @field_validator("OUTCOME_EVALUATOR_TICKERS", mode="before")
    @classmethod
    def parse_outcome_evaluator_tickers(cls, v: Any) -> list[str]:
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
