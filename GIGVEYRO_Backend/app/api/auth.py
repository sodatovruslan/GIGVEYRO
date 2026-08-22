import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account
from app.core.security import TokenError, TokenType, decode_token
from app.db.session import get_db
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.audit import AuditRepository
from app.repositories.auth_session import AuthSessionRepository
from app.schemas.account import AccountRead
from app.schemas.auth import LoginRequest, RefreshTokenRequest, TokenResponse
from app.schemas.auth_session import AuthSessionListResponse, AuthSessionRead, LogoutAllResponse
from app.services.audit import AuditService
from app.services.auth import (
    AuthenticationError,
    AuthService,
    SessionNotFoundError,
    TokenPair,
    TokenReuseError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(AccountRepository(db), AuthSessionRepository(db))


def _audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(AuditRepository(db))


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _token_response(token_pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        access_expires_in=token_pair.access_expires_in,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    service: AuthService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> TokenResponse:
    try:
        account = await service.authenticate(payload.username, payload.password)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
        ) from exc

    token_pair = await service.login(
        account,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
    )
    await audit.log_action(
        action="auth.login",
        entity_type="account",
        entity_id=str(account.id),
        actor_account_id=account.id,
        actor_role=account.role.value,
    )
    return _token_response(token_pair)


@router.get("/me", response_model=AccountRead)
async def read_current_account(account: Account = Depends(get_current_account)) -> Account:
    return account


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    payload: RefreshTokenRequest,
    request: Request,
    service: AuthService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> TokenResponse:
    try:
        token_pair = await service.refresh(
            payload.refresh_token,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
    except TokenReuseError as exc:
        await audit.log_action(
            action="auth.session_revoked",
            entity_type="auth_session",
            entity_id=str(exc.session_id),
            actor_account_id=exc.account_id,
            audit_metadata={"reason": "reuse_detected"},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="refresh token reuse detected; session revoked",
        ) from exc
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid refresh token",
        ) from exc

    return _token_response(token_pair)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshTokenRequest,
    service: AuthService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> None:
    actor_account_id: str | None = None
    try:
        actor_account_id = decode_token(payload.refresh_token, TokenType.REFRESH).get("sub")
    except TokenError:
        pass

    await service.logout(payload.refresh_token)
    await audit.log_action(
        action="auth.logout",
        entity_type="auth_session",
        actor_account_id=uuid.UUID(actor_account_id) if actor_account_id else None,
    )


@router.post("/logout-all", response_model=LogoutAllResponse)
async def logout_all(
    account: Account = Depends(get_current_account),
    service: AuthService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> LogoutAllResponse:
    revoked_count = await service.logout_all(account.id)
    await audit.log_action(
        action="auth.logout_all",
        entity_type="account",
        entity_id=str(account.id),
        actor_account_id=account.id,
        actor_role=account.role.value,
        audit_metadata={"revoked_count": revoked_count},
    )
    return LogoutAllResponse(revoked_count=revoked_count)


@router.get("/sessions", response_model=AuthSessionListResponse)
async def list_sessions(
    request: Request,
    account: Account = Depends(get_current_account),
    service: AuthService = Depends(_service),
) -> AuthSessionListResponse:
    auth_header = request.headers.get("authorization", "")
    current_session_id: str | None = None
    if auth_header.lower().startswith("bearer "):
        try:
            current_session_id = decode_token(auth_header[7:], TokenType.ACCESS).get("session_id")
        except TokenError:
            current_session_id = None

    sessions = await service.list_sessions(account.id)
    items = [
        AuthSessionRead.model_validate(session).model_copy(
            update={"is_current": str(session.id) == current_session_id}
        )
        for session in sessions
    ]
    return AuthSessionListResponse(items=items)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID,
    account: Account = Depends(get_current_account),
    service: AuthService = Depends(_service),
    audit: AuditService = Depends(_audit_service),
) -> None:
    try:
        await service.revoke_session(account.id, session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="session not found"
        ) from exc

    await audit.log_action(
        action="auth.session_revoked",
        entity_type="auth_session",
        entity_id=str(session_id),
        actor_account_id=account.id,
        actor_role=account.role.value,
        audit_metadata={"reason": "revoked_by_user"},
    )
