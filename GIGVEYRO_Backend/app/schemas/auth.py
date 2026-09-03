from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import PasswordStr


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: PasswordStr


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    access_expires_in: int


class TwoFactorRequiredResponse(BaseModel):
    two_factor_required: Literal[True] = True
    challenge_token: str
    expires_in: int


class TwoFactorSetupRequiredResponse(BaseModel):
    two_factor_setup_required: Literal[True] = True
    setup_token: str
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    current_password: PasswordStr
    new_password: PasswordStr
    code: str | None = Field(default=None, min_length=6, max_length=32)
