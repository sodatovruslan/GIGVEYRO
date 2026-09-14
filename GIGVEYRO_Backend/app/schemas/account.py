import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.enums.account import UserRole


class AccountBase(BaseModel):
    username: str
    role: UserRole
    full_name: str
    email: str | None = None
    phone: str | None = None


class AccountRead(AccountBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    is_verified: bool
    team_lead_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
