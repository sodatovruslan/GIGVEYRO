import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums.api_key import ApiKeyStatus


class ApiKeyCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    key_prefix: str
    status: ApiKeyStatus
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    """Returned only from the create endpoint - the raw key is never
    retrievable again after this response."""

    raw_key: str


class ApiKeyListResponse(BaseModel):
    items: list[ApiKeyRead]
    total: int
    limit: int
    offset: int
