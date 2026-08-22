from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

CurrentPassword = Annotated[str, Field(min_length=1, max_length=200)]
TotpCode = Annotated[str, Field(min_length=6, max_length=6, pattern=r"^\d{6}$")]


class TwoFactorSetupStartRequest(BaseModel):
    password: CurrentPassword


class TwoFactorSetupStartResponse(BaseModel):
    otpauth_uri: str
    manual_key: str
    expires_at: datetime


class TwoFactorSetupConfirmRequest(BaseModel):
    totp_code: TotpCode


class TwoFactorSetupConfirmResponse(BaseModel):
    enabled_at: datetime
    recovery_codes: list[str]


class TwoFactorVerifyRequest(BaseModel):
    challenge_token: str
    code: str = Field(min_length=6, max_length=32)


class TwoFactorDisableRequest(BaseModel):
    password: CurrentPassword
    code: str = Field(min_length=6, max_length=32)


class TwoFactorRegenerateRequest(BaseModel):
    password: CurrentPassword
    totp_code: TotpCode


class TwoFactorRegenerateResponse(BaseModel):
    recovery_codes: list[str]


class TwoFactorStatusResponse(BaseModel):
    enabled: bool
    enabled_at: datetime | None = None
    recovery_codes_remaining: int = 0
