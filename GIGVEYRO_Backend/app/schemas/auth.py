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


class RefreshTokenRequest(BaseModel):
    refresh_token: str
