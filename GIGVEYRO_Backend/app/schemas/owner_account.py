from pydantic import BaseModel, Field, field_validator

from app.enums.account import UserRole
from app.schemas.account import AccountRead
from app.schemas.common import PasswordStr


class OwnerAccountCreate(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: PasswordStr
    role: UserRole
    full_name: str = Field(min_length=1, max_length=255)
    email: str | None = None
    phone: str | None = None

    @field_validator("role")
    @classmethod
    def role_must_be_manageable(cls, value: UserRole) -> UserRole:
        if value == UserRole.OWNER:
            raise ValueError("role must be 'user' or 'merchant'")
        return value


class OwnerAccountUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = None
    phone: str | None = None


class OwnerPasswordReset(BaseModel):
    new_password: PasswordStr


class AccountListResponse(BaseModel):
    items: list[AccountRead]
    total: int
    limit: int
    offset: int
