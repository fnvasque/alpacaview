import logging
import logging.config
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

import app.models  # noqa: F401 — registers all ORM models with Base.metadata
from app.config import get_settings
from app.database import init_db
from app.routers import resend_inbound, webhook


class _SecretFilter(logging.Filter):
    """Drop 'secret' key from log record extra fields before emission."""

    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "secret"):
            del record.secret  # type: ignore[attr-defined]
        return True


def _configure_logging(log_level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_SecretFilter())
    handler.setFormatter(
        logging.Formatter(
            fmt='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
    )
    root = logging.getLogger()
    root.setLevel(log_level.upper())
    root.handlers = [handler]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging(settings.LOG_LEVEL)

    application = FastAPI(
        title="AlpacaView — Trading System V0",
        description="Paper-first webhook receiver and risk engine. approved=True means risk-approved for observability only. V0 does not execute orders.",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(webhook.router)
    application.include_router(resend_inbound.router)
    return application


app = create_app()
