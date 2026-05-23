from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DashboardSettings(BaseSettings):
    DATABASE_URL: Optional[str] = None
    DASHBOARD_DB_URL: Optional[str] = None

    @model_validator(mode="after")
    def resolve_db_url(self) -> "DashboardSettings":
        if not self.DASHBOARD_DB_URL:
            object.__setattr__(
                self,
                "DASHBOARD_DB_URL",
                self.DATABASE_URL or "sqlite:///./alpacaview.db",
            )
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
