import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.url_safety import UnsafeWebhookURLError, validate_webhook_url_syntax
from app.enums.webhook import WebhookDeliveryStatus, WebhookEventType, WebhookStatus

_ALLOWED_EVENT_TYPES = {member.value for member in WebhookEventType}


def _validate_event_types(value: list[str]) -> list[str]:
    unknown = set(value) - _ALLOWED_EVENT_TYPES
    if unknown:
        raise ValueError(f"unknown event type(s): {', '.join(sorted(unknown))}")
    return value


def _validate_url(value: str) -> str:
    # Structural check only (https:// + hostname present) - no network I/O
    # is possible from a Pydantic validator. The real SSRF-safety check
    # (DNS resolution + private-address rejection) runs in WebhookService,
    # and again immediately before every delivery attempt.
    try:
        return validate_webhook_url_syntax(value)
    except UnsafeWebhookURLError as exc:
        raise ValueError(str(exc)) from exc


class WebhookCreate(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    event_types: list[str] = Field(min_length=1)

    _validate_event_types = field_validator("event_types")(_validate_event_types)
    _validate_url = field_validator("url")(_validate_url)


class WebhookUpdate(BaseModel):
    url: str | None = Field(default=None, min_length=1, max_length=500)
    status: WebhookStatus | None = None
    event_types: list[str] | None = Field(default=None, min_length=1)

    @field_validator("event_types")
    @classmethod
    def _check_event_types(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _validate_event_types(value)

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        return None if value is None else _validate_url(value)


class WebhookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    url: str
    event_types: list[str]
    status: WebhookStatus
    created_at: datetime
    updated_at: datetime


class WebhookCreated(WebhookRead):
    """Returned only from the create endpoint - the signing secret is
    never retrievable again after this response."""

    secret: str


class WebhookListResponse(BaseModel):
    items: list[WebhookRead]
    total: int
    limit: int
    offset: int


class WebhookDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    webhook_id: uuid.UUID
    event_type: str
    payload: dict[str, Any]
    status: WebhookDeliveryStatus
    attempts: int
    max_attempts: int
    next_attempt_at: datetime | None
    last_response_status: int | None
    last_response_snippet: str | None
    last_error: str | None
    created_at: datetime
    delivered_at: datetime | None


class WebhookDeliveryListResponse(BaseModel):
    items: list[WebhookDeliveryRead]
    total: int
    limit: int
    offset: int
