import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import enforce_rate_limit
from app.core.security import TokenError, TokenType, decode_token
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.api_key import ApiKeyStatus
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.api_key import ApiKeyRepository
from app.repositories.auth_session import AuthSessionRepository
from app.services.api_key import ApiKeyService

# auto_error=False so a missing token is reported as our own 401, matching
# every other authentication failure instead of FastAPI's default 403.
_bearer_scheme = HTTPBearer(auto_error=False)


async def _resolve_access_account(
    credentials: HTTPAuthorizationCredentials | None, db: AsyncSession
) -> Account | None:
    """Core of get_current_account, but returns None instead of raising.

    Split out so other dependencies (e.g. the required-2FA onboarding
    resolver) can attempt a normal access token first without duplicating
    the session-validity check, and fall back to a different token purpose
    on failure.
    """
    if credentials is None:
        return None

    try:
        payload = decode_token(credentials.credentials, TokenType.ACCESS)
    except TokenError:
        return None

    account = await AccountRepository(db).get_by_id(uuid.UUID(payload["sub"]))
    if account is None or not account.is_active:
        return None

    # Tokens minted through the real login/refresh flow carry a session_id,
    # so a revoked/logged-out session is rejected immediately instead of
    # staying valid until the access token's natural expiry. Tokens without
    # a session_id (e.g. bootstrap scripts) fall back to the account check
    # above only.
    session_id = payload.get("session_id")
    if session_id is not None:
        auth_session = await AuthSessionRepository(db).get_by_id(uuid.UUID(session_id))
        if (
            auth_session is None
            or auth_session.revoked_at is not None
            or auth_session.expires_at <= datetime.now(UTC)
        ):
            return None

    return account


async def get_current_account(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Account:
    account = await _resolve_access_account(credentials, db)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return account


async def get_merchant_via_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Account:
    """Authenticates the public invoice API using a merchant-issued API key
    (Authorization: Bearer <key>) instead of a session access token."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid or missing API key",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized

    client_ip = request.client.host if request.client else "127.0.0.1"
    await enforce_rate_limit(
        f"api_key_auth:{client_ip}",
        settings.API_KEY_AUTH_RATE_LIMIT_REQUESTS,
        settings.API_KEY_AUTH_RATE_LIMIT_WINDOW_SECONDS,
    )

    api_key = await ApiKeyService(ApiKeyRepository(db)).authenticate(credentials.credentials)
    if api_key is None or api_key.status != ApiKeyStatus.ACTIVE:
        raise unauthorized

    account = await AccountRepository(db).get_by_id(api_key.merchant_id)
    if account is None or not account.is_active or account.role != UserRole.MERCHANT:
        raise unauthorized
    return account


def require_roles(*roles: UserRole) -> Callable[..., Awaitable[Account]]:
    async def dependency(account: Account = Depends(get_current_account)) -> Account:
        if account.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient permissions",
            )
        return account

    return dependency


@dataclass(frozen=True)
class TwoFactorSetupActor:
    account: Account
    # False when authenticated via a normal access token (the account chose
    # to enable 2FA voluntarily) - the endpoint must still independently
    # verify the caller's password for this sensitive action. True when
    # authenticated via a two_factor_setup_required token (OWNER_2FA_REQUIRED
    # forced onboarding right after login) - the token itself already proves
    # the password was just verified during /auth/login, so asking again
    # would just be onboarding friction.
    password_verified: bool


async def get_two_factor_setup_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> TwoFactorSetupActor:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    account = await _resolve_access_account(credentials, db)
    if account is not None:
        return TwoFactorSetupActor(account=account, password_verified=False)

    if credentials is None:
        raise unauthorized

    try:
        payload = decode_token(credentials.credentials, TokenType.TWO_FACTOR_SETUP_REQUIRED)
    except TokenError as exc:
        raise unauthorized from exc

    setup_account = await AccountRepository(db).get_by_id(uuid.UUID(payload["sub"]))
    if setup_account is None or not setup_account.is_active or setup_account.role != UserRole.OWNER:
        raise unauthorized

    return TwoFactorSetupActor(account=setup_account, password_verified=True)
