import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.core.security import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.account import Account
from app.models.auth_session import AuthSession
from app.repositories.account import AccountRepository
from app.repositories.auth_session import AuthSessionRepository

# Used to keep authenticate() taking roughly constant time whether the
# username exists or not, so response timing can't be used to enumerate
# valid usernames.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing-safety")

_MAX_USER_AGENT_LENGTH = 255
_MAX_IP_ADDRESS_LENGTH = 64


class AuthenticationError(Exception):
    """Raised when login credentials are invalid or the account cannot authenticate."""


class TokenReuseError(Exception):
    """Raised when an already-rotated refresh token is presented again.

    Signals that the whole session was just revoked as a reaction.
    """

    def __init__(self, account_id: uuid.UUID, session_id: uuid.UUID):
        self.account_id = account_id
        self.session_id = session_id
        super().__init__("refresh token has already been rotated")


class SessionNotFoundError(Exception):
    """Raised when a caller tries to act on a session that doesn't belong to them."""


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_in: int


def _device_name(user_agent: str | None) -> str | None:
    if not user_agent:
        return None
    ua = user_agent.lower()
    if "mobile" in ua or "android" in ua or "iphone" in ua:
        return "Mobile device"
    if "windows" in ua:
        return "Windows"
    if "macintosh" in ua or "mac os" in ua:
        return "Mac"
    if "linux" in ua:
        return "Linux"
    return "Unknown device"


class AuthService:
    def __init__(
        self,
        account_repository: AccountRepository,
        session_repository: AuthSessionRepository,
    ):
        self._repository = account_repository
        self._sessions = session_repository

    async def authenticate(self, username: str, password: str) -> Account:
        account = await self._repository.get_by_username(username)
        if account is None:
            verify_password(password, _DUMMY_PASSWORD_HASH)
            raise AuthenticationError("invalid username or password")

        if not verify_password(password, account.password_hash) or not account.is_active:
            raise AuthenticationError("invalid username or password")

        return account

    async def login(
        self,
        account: Account,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        now = datetime.now(UTC)
        session = AuthSession(
            account_id=account.id,
            refresh_token_hash="",
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            last_used_at=now,
            user_agent=user_agent[:_MAX_USER_AGENT_LENGTH] if user_agent else None,
            ip_address=ip_address[:_MAX_IP_ADDRESS_LENGTH] if ip_address else None,
            device_name=_device_name(user_agent),
        )
        session = await self._sessions.create(session)

        refresh_token = create_refresh_token(account.id, account.role.value, session.id)
        session.refresh_token_hash = hash_refresh_token(refresh_token)
        await self._sessions.update(session)

        access_token = create_access_token(account.id, account.role.value, session.id)
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def refresh(
        self,
        refresh_token: str,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        try:
            payload = decode_token(refresh_token, TokenType.REFRESH)
        except TokenError as exc:
            raise AuthenticationError("invalid refresh token") from exc

        session_id = payload.get("session_id")
        if not session_id:
            raise AuthenticationError("invalid refresh token")

        session = await self._sessions.get_by_id_for_update(uuid.UUID(session_id))
        if session is None:
            raise AuthenticationError("invalid refresh token")

        now = datetime.now(UTC)
        if session.revoked_at is not None:
            raise AuthenticationError("invalid refresh token")
        if session.expires_at <= now:
            raise AuthenticationError("invalid refresh token")

        if hash_refresh_token(refresh_token) != session.refresh_token_hash:
            # Reuse of a token that was already superseded by a later
            # rotation (or a forged one for a real session). Treat the
            # whole session as compromised.
            session.revoked_at = now
            session.revoked_reason = "reuse_detected"
            await self._sessions.update(session)
            raise TokenReuseError(session.account_id, session.id)

        account = await self._repository.get_by_id(session.account_id)
        if account is None or not account.is_active:
            session.revoked_at = now
            session.revoked_reason = "account_inactive"
            await self._sessions.update(session)
            raise AuthenticationError("invalid refresh token")

        new_refresh_token = create_refresh_token(account.id, account.role.value, session.id)
        session.refresh_token_hash = hash_refresh_token(new_refresh_token)
        session.rotation_counter += 1
        session.last_used_at = now
        if user_agent:
            session.user_agent = user_agent[:_MAX_USER_AGENT_LENGTH]
            session.device_name = _device_name(user_agent)
        if ip_address:
            session.ip_address = ip_address[:_MAX_IP_ADDRESS_LENGTH]
        await self._sessions.update(session)

        access_token = create_access_token(account.id, account.role.value, session.id)
        return TokenPair(
            access_token=access_token,
            refresh_token=new_refresh_token,
            access_expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def logout(self, refresh_token: str) -> None:
        # Idempotent by design: an already-invalid/expired token is treated
        # as "nothing to do" rather than an error, since the caller's goal
        # (not being logged in) is already satisfied either way.
        try:
            payload = decode_token(refresh_token, TokenType.REFRESH)
        except TokenError:
            return

        session_id = payload.get("session_id")
        if not session_id:
            return

        session = await self._sessions.get_by_id(uuid.UUID(session_id))
        if session is None or session.revoked_at is not None:
            return

        session.revoked_at = datetime.now(UTC)
        session.revoked_reason = "logout"
        await self._sessions.update(session)

    async def logout_all(
        self, account_id: uuid.UUID, *, except_session_id: uuid.UUID | None = None
    ) -> int:
        return await self._sessions.revoke_all_for_account(
            account_id, reason="logout_all", except_session_id=except_session_id
        )

    async def list_sessions(self, account_id: uuid.UUID) -> list[AuthSession]:
        return await self._sessions.list_active_for_account(account_id)

    async def revoke_session(self, account_id: uuid.UUID, session_id: uuid.UUID) -> None:
        session = await self._sessions.get_by_id(session_id)
        if session is None or session.account_id != account_id or session.revoked_at is not None:
            raise SessionNotFoundError()

        session.revoked_at = datetime.now(UTC)
        session.revoked_reason = "revoked_by_user"
        await self._sessions.update(session)

    async def cleanup_expired_sessions(self, *, retention_days: int | None = None) -> int:
        """Delete sessions that expired more than `retention_days` ago.

        Not scheduled by this service - a production worker/cron should
        call this periodically (see SECURITY.md).
        """
        days = (
            retention_days
            if retention_days is not None
            else settings.SESSION_CLEANUP_RETENTION_DAYS
        )
        cutoff = datetime.now(UTC) - timedelta(days=days)
        return await self._sessions.prune_expired(cutoff)
