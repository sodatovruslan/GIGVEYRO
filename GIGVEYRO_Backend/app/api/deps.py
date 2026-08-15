import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, TokenType, decode_token
from app.db.session import get_db
from app.enums.account import UserRole
from app.models.account import Account
from app.repositories.account import AccountRepository

# auto_error=False so a missing token is reported as our own 401, matching
# every other authentication failure instead of FastAPI's default 403.
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_account(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Account:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    try:
        payload = decode_token(credentials.credentials, TokenType.ACCESS)
    except TokenError as exc:
        raise unauthorized from exc

    account = await AccountRepository(db).get_by_id(uuid.UUID(payload["sub"]))
    if account is None or not account.is_active:
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
