import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuthSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    device_name: str | None = None
    is_current: bool = False


class AuthSessionListResponse(BaseModel):
    items: list[AuthSessionRead]


class LogoutAllResponse(BaseModel):
    revoked_count: int
