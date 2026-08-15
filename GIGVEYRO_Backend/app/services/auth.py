import uuid
from dataclasses import dataclass

from app.core.config import settings
from app.core.security import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.account import Account
from app.repositories.account import AccountRepository

# Used to keep authenticate() taking roughly constant time whether the
# username exists or not, so response timing can't be used to enumerate
# valid usernames.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing-safety")


class AuthenticationError(Exception):
    """Raised when login credentials are invalid or the account cannot authenticate."""


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_in: int


class AuthService:
    def __init__(self, repository: AccountRepository):
        self._repository = repository

    async def authenticate(self, username: str, password: str) -> Account:
        account = await self._repository.get_by_username(username)
        if account is None:
            verify_password(password, _DUMMY_PASSWORD_HASH)
            raise AuthenticationError("invalid username or password")

        if not verify_password(password, account.password_hash) or not account.is_active:
            raise AuthenticationError("invalid username or password")

        return account

    def create_token_pair(self, account: Account) -> TokenPair:
        return TokenPair(
            access_token=create_access_token(account.id, account.role.value),
            refresh_token=create_refresh_token(account.id, account.role.value),
            access_expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def refresh(self, refresh_token: str) -> TokenPair:
        # Stateless refresh: this only verifies the token's signature, type,
        # and expiry. There is no server-side session/revocation store yet,
        # so a still-valid old refresh token keeps working after this call
        # issues a new one (no true rotation). See Stage 3 report.
        try:
            payload = decode_token(refresh_token, TokenType.REFRESH)
        except TokenError as exc:
            raise AuthenticationError("invalid refresh token") from exc

        account = await self._repository.get_by_id(uuid.UUID(payload["sub"]))
        if account is None or not account.is_active:
            raise AuthenticationError("invalid refresh token")

        return self.create_token_pair(account)
