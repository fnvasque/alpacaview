import logging
from typing import Optional

import httpx
from fastapi import Depends
from pydantic import BaseModel, ConfigDict

from app.config import Settings, get_settings

log = logging.getLogger(__name__)


class ResendClientError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class ResendEmailContent(BaseModel):
    id: str
    text: Optional[str] = None
    html: Optional[str] = None

    model_config = ConfigDict(extra="ignore")


class ResendClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def fetch_email(self, email_id: str) -> ResendEmailContent:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"https://api.resend.com/emails/receiving/{email_id}",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            log.warning(
                "resend_fetch_http_error",
                extra={
                    "stage": "resend_fetch_http_error",
                    "email_id": email_id,
                    "status_code": e.response.status_code,
                },
            )
            raise ResendClientError(f"resend_api_error: {type(e).__name__}")
        except httpx.RequestError as e:
            raise ResendClientError(f"resend_api_error: {type(e).__name__}")
        return ResendEmailContent.model_validate(response.json())


def get_resend_client(settings: Settings = Depends(get_settings)) -> ResendClient:
    return ResendClient(api_key=settings.RESEND_API_KEY or "")
