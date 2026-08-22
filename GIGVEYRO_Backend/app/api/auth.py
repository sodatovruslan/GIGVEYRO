import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    TwoFactorSetupActor,
    get_current_account,
    get_two_factor_setup_actor,
    require_roles,
)
from app.core.config import settings
from app.core.security import (
    TokenError,
    TokenType,
    create_two_factor_challenge_token,
    create_two_factor_setup_required_token,
    decode_token,
)
from app.core.totp_crypto import decrypt_totp_secret
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.notification import NotificationType
from app.infra.redis_rate_limiter import RedisRateLimiter
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.repositories.audit import AuditRepository
from app.repositories.auth_session import AuthSessionRepository
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.repositories.two_factor import (
    AccountTwoFactorRepository,
    PendingTwoFactorSetupRepository,
    TwoFactorChallengeRepository,
    TwoFactorRecoveryCodeRepository,
)
from app.schemas.account import AccountRead
from app.schemas.auth import (
    LoginRequest,
    RefreshTokenRequest,
    TokenResponse,
    TwoFactorRequiredResponse,
    TwoFactorSetupRequiredResponse,
)
from app.schemas.auth_session import AuthSessionListResponse, AuthSessionRead, LogoutAllResponse
from app.schemas.two_factor import (
    TwoFactorDisableRequest,
    TwoFactorRegenerateRequest,
    TwoFactorRegenerateResponse,
    TwoFactorSetupConfirmRequest,
    TwoFactorSetupConfirmResponse,
    TwoFactorSetupStartRequest,
    TwoFactorSetupStartResponse,
    TwoFactorStatusResponse,
    TwoFactorVerifyRequest,
)
from app.services.audit import AuditService
from app.services.auth import (
    AuthenticationError,
    AuthService,
    SessionNotFoundError,
    TokenPair,
    TokenReuseError,
)
from app.services.notification import NotificationService
from app.services.telegram_provider import MockTelegramProvider
from app.services.two_factor import (
    ChallengeInvalidError,
    ChallengeLockedError,
    InvalidCodeError,
    InvalidPasswordError,
    SetupExpiredError,
    TwoFactorAlreadyEnabledError,
    TwoFactorNotEnabledError,
    TwoFactorService,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_two_factor_rate_limiter = RedisRateLimiter()


def _service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(AccountRepository(db), AuthSessionRepository(db))


def _audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(AuditRepository(db))


def _two_factor_service(db: AsyncSession = Depends(get_db)) -> TwoFactorService:
    return TwoFactorService(
        AccountTwoFactorRepository(db),
        PendingTwoFactorSetupRepository(db),
        TwoFactorRecoveryCodeRepository(db),
        TwoFactorChallengeRepository(db),
    )


def _notification_service(db: AsyncSession = Depends(get_db)) -> NotificationService:
    return NotificationService(
        NotificationRepository(db), TelegramLinkRepository(db), MockTelegramProvider()
    )


async def _notify_owner_security_event(
    notifications: NotificationService, account: Account, *, title: str, message: str
) -> None:
    # Security notifications are currently scoped to OWNER only (the only
    # role that can have 2FA / active-session self-management in this
    # stage) - same emit_notification() call other domains already use for
    # deposits/withdrawals/appeals, no changes to the notification system
    # itself.
    if account.role != UserRole.OWNER:
        return
    await notifications.emit_notification(
        account.id, NotificationType.SECURITY_EVENT, title=title, message=message
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _token_response(token_pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        access_expires_in=token_pair.access_expires_in,
    )


def _bearer_session_id(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    try:
        return decode_token(auth_header[7:], TokenType.ACCESS).get("session_id")
    except TokenError:
        return None


async def _enforce_two_factor_rate_limit(key: str) -> None:
    # Same rationale as the login limiter (app/core/middleware.py): a
    # Redis outage must not silently remove brute-force protection from
    # 2FA code verification.
    limited = await _two_factor_rate_limiter.is_rate_limited(
        key,
        settings.TWO_FACTOR_VERIFY_RATE_LIMIT_REQUESTS,
        settings.TWO_FACTOR_VERIFY_RATE_LIMIT_WINDOW_SECONDS,
        fail_mode="fallback",
    )
    if limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many verification attempts, try again later",
            headers={"Retry-After": str(settings.TWO_FACTOR_VERIFY_RATE_LIMIT_WINDOW_SECONDS)},
        )


@router.post(
    "/login",
    response_model=TokenResponse | TwoFactorRequiredResponse | TwoFactorSetupRequiredResponse,
)
async def login(
    payload: LoginRequest,
    request: Request,
    service: AuthService = Depends(_service),
    two_factor_service: TwoFactorService = Depends(_two_factor_service),
    audit: AuditService = Depends(_audit_service),
) -> TokenResponse | TwoFactorRequiredResponse | TwoFactorSetupRequiredResponse:
    try:
        account = await service.authenticate(payload.username, payload.password)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
        ) from exc

    two_factor = await two_factor_service.get_status(account.id)
    if two_factor is not None:
        challenge = await two_factor_service.create_challenge(account)
        challenge_token = create_two_factor_challenge_token(
            account.id,
            account.role.value,
            challenge.id,
            settings.TWO_FACTOR_CHALLENGE_EXPIRE_SECONDS,
        )
        return TwoFactorRequiredResponse(
            challenge_token=challenge_token,
            expires_in=settings.TWO_FACTOR_CHALLENGE_EXPIRE_SECONDS,
        )

    if account.role == UserRole.OWNER and settings.OWNER_2FA_REQUIRED:
        # Credentials are valid but this OWNER has no 2FA configured yet and
        # enforcement is on: no real session is issued. The setup_token only
        # authorizes the onboarding setup/confirm endpoints (see
        # api/deps.py:get_two_factor_setup_actor) - it cannot reach any other
        # protected endpoint, matching the login-challenge token's isolation.
        setup_expires_seconds = settings.TWO_FACTOR_SETUP_EXPIRE_MINUTES * 60
        setup_token = create_two_factor_setup_required_token(
            account.id, account.role.value, setup_expires_seconds
        )
        return TwoFactorSetupRequiredResponse(
            setup_token=setup_token, expires_in=setup_expires_seconds
        )

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


@router.post("/2fa/verify", response_model=TokenResponse)
async def verify_two_factor(
    payload: TwoFactorVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: AuthService = Depends(_service),
    two_factor_service: TwoFactorService = Depends(_two_factor_service),
    audit: AuditService = Depends(_audit_service),
    notifications: NotificationService = Depends(_notification_service),
) -> TokenResponse:
    # 410 Gone: the challenge itself is dead (expired/consumed/locked/malformed
    # token) - the client must restart login, retrying with a new code won't
    # help. 401: the challenge is still alive but this specific code was
    # wrong - the client may retry.
    challenge_dead = HTTPException(
        status_code=status.HTTP_410_GONE, detail="invalid or expired challenge"
    )
    try:
        payload_claims = decode_token(payload.challenge_token, TokenType.TWO_FACTOR_CHALLENGE)
    except TokenError as exc:
        raise challenge_dead from exc

    account_id = uuid.UUID(payload_claims["sub"])
    challenge_id = uuid.UUID(payload_claims["jti"])

    await _enforce_two_factor_rate_limit(f"2fa_verify:{account_id}")

    account = await AccountRepository(db).get_by_id(account_id)
    if account is None or not account.is_active:
        raise challenge_dead

    try:
        used_recovery = await two_factor_service.verify_challenge(
            challenge_id, account, payload.code
        )
    except (ChallengeInvalidError, ChallengeLockedError) as exc:
        raise challenge_dead from exc
    except InvalidCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid code"
        ) from exc

    token_pair = await service.login(
        account,
        user_agent=request.headers.get("user-agent"),
        ip_address=_client_ip(request),
    )
    await audit.log_action(
        action="auth.2fa_recovery_used" if used_recovery else "auth.2fa_login_success",
        entity_type="account",
        entity_id=str(account.id),
        actor_account_id=account.id,
        actor_role=account.role.value,
    )
    await audit.log_action(
        action="auth.login",
        entity_type="account",
        entity_id=str(account.id),
        actor_account_id=account.id,
        actor_role=account.role.value,
    )
    if used_recovery:
        await _notify_owner_security_event(
            notifications,
            account,
            title="Recovery code used",
            message="A recovery code was used to sign in to your account.",
        )
    return _token_response(token_pair)


@router.get("/2fa/status", response_model=TwoFactorStatusResponse)
async def two_factor_status(
    account: Account = Depends(get_current_account),
    two_factor_service: TwoFactorService = Depends(_two_factor_service),
) -> TwoFactorStatusResponse:
    record = await two_factor_service.get_status(account.id)
    if record is None:
        return TwoFactorStatusResponse(enabled=False)

    remaining = await two_factor_service.count_unused_recovery_codes(account.id)
    return TwoFactorStatusResponse(
        enabled=True, enabled_at=record.enabled_at, recovery_codes_remaining=remaining
    )


@router.post("/2fa/setup/start", response_model=TwoFactorSetupStartResponse)
async def start_two_factor_setup(
    payload: TwoFactorSetupStartRequest,
    actor: Annotated[TwoFactorSetupActor, Depends(get_two_factor_setup_actor)],
    two_factor_service: TwoFactorService = Depends(_two_factor_service),
    audit: AuditService = Depends(_audit_service),
) -> TwoFactorSetupStartResponse:
    account = actor.account
    try:
        pending = await two_factor_service.start_setup(
            account, payload.password, password_verified=actor.password_verified
        )
    except InvalidPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid password"
        ) from exc
    except TwoFactorAlreadyEnabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="two-factor authentication already enabled"
        ) from exc

    secret = decrypt_totp_secret(pending.encrypted_secret)
    await audit.log_action(
        action="auth.2fa_setup_started",
        entity_type="account",
        entity_id=str(account.id),
        actor_account_id=account.id,
        actor_role=account.role.value,
    )
    return TwoFactorSetupStartResponse(
        otpauth_uri=two_factor_service.build_otpauth_uri(account, secret),
        manual_key=two_factor_service.format_manual_key(secret),
        expires_at=pending.expires_at,
    )


@router.post("/2fa/setup/confirm", response_model=TwoFactorSetupConfirmResponse)
async def confirm_two_factor_setup(
    payload: TwoFactorSetupConfirmRequest,
    request: Request,
    actor: Annotated[TwoFactorSetupActor, Depends(get_two_factor_setup_actor)],
    service: AuthService = Depends(_service),
    two_factor_service: TwoFactorService = Depends(_two_factor_service),
    audit: AuditService = Depends(_audit_service),
    notifications: NotificationService = Depends(_notification_service),
) -> TwoFactorSetupConfirmResponse:
    account = actor.account
    try:
        record, recovery_codes = await two_factor_service.confirm_setup(
            account, payload.totp_code
        )
    except SetupExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="setup expired, please start again"
        ) from exc
    except InvalidCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid code"
        ) from exc

    if actor.password_verified:
        # Forced onboarding (OWNER_2FA_REQUIRED): no session existed before
        # this call, so this is where one is finally created. Any session
        # from before 2FA enforcement kicked in is revoked outright - there
        # is no "current session" to except yet.
        revoked_count = await service.logout_all(account.id)
        token_pair = await service.login(
            account,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
        await audit.log_action(
            action="auth.2fa_enabled",
            entity_type="account",
            entity_id=str(account.id),
            actor_account_id=account.id,
            actor_role=account.role.value,
            audit_metadata={"other_sessions_revoked": revoked_count, "forced_onboarding": True},
        )
        await audit.log_action(
            action="auth.login",
            entity_type="account",
            entity_id=str(account.id),
            actor_account_id=account.id,
            actor_role=account.role.value,
        )
        await _notify_owner_security_event(
            notifications,
            account,
            title="Two-factor authentication enabled",
            message="Two-factor authentication was enabled on your account.",
        )
        return TwoFactorSetupConfirmResponse(
            enabled_at=record.enabled_at,
            recovery_codes=recovery_codes,
            access_token=token_pair.access_token,
            refresh_token=token_pair.refresh_token,
            access_expires_in=token_pair.access_expires_in,
        )

    current_session_id = _bearer_session_id(request)
    revoked_count = await service.logout_all(
        account.id,
        except_session_id=uuid.UUID(current_session_id) if current_session_id else None,
    )
    await audit.log_action(
        action="auth.2fa_enabled",
        entity_type="account",
        entity_id=str(account.id),
        actor_account_id=account.id,
        actor_role=account.role.value,
        audit_metadata={"other_sessions_revoked": revoked_count},
    )
    await _notify_owner_security_event(
        notifications,
        account,
        title="Two-factor authentication enabled",
        message="Two-factor authentication was enabled on your account.",
    )
    return TwoFactorSetupConfirmResponse(
        enabled_at=record.enabled_at, recovery_codes=recovery_codes
    )


@router.post("/2fa/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable_two_factor(
    payload: TwoFactorDisableRequest,
    request: Request,
    account: Annotated[Account, Depends(require_roles(UserRole.OWNER))],
    service: AuthService = Depends(_service),
    two_factor_service: TwoFactorService = Depends(_two_factor_service),
    audit: AuditService = Depends(_audit_service),
    notifications: NotificationService = Depends(_notification_service),
) -> None:
    try:
        await two_factor_service.disable(account, payload.password, payload.code)
    except InvalidPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid password"
        ) from exc
    except TwoFactorNotEnabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="two-factor authentication not enabled"
        ) from exc
    except InvalidCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid code"
        ) from exc

    current_session_id = _bearer_session_id(request)
    revoked_count = await service.logout_all(
        account.id,
        except_session_id=uuid.UUID(current_session_id) if current_session_id else None,
    )
    await audit.log_action(
        action="auth.2fa_disabled",
        entity_type="account",
        entity_id=str(account.id),
        actor_account_id=account.id,
        actor_role=account.role.value,
        audit_metadata={"other_sessions_revoked": revoked_count},
    )
    await _notify_owner_security_event(
        notifications,
        account,
        title="Two-factor authentication disabled",
        message="Two-factor authentication was disabled on your account.",
    )


@router.post("/2fa/recovery/regenerate", response_model=TwoFactorRegenerateResponse)
async def regenerate_recovery_codes(
    payload: TwoFactorRegenerateRequest,
    account: Annotated[Account, Depends(require_roles(UserRole.OWNER))],
    two_factor_service: TwoFactorService = Depends(_two_factor_service),
    audit: AuditService = Depends(_audit_service),
) -> TwoFactorRegenerateResponse:
    try:
        codes = await two_factor_service.regenerate_recovery_codes(
            account, payload.password, payload.totp_code
        )
    except InvalidPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid password"
        ) from exc
    except TwoFactorNotEnabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="two-factor authentication not enabled"
        ) from exc
    except InvalidCodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid code"
        ) from exc

    await audit.log_action(
        action="auth.2fa_recovery_regenerated",
        entity_type="account",
        entity_id=str(account.id),
        actor_account_id=account.id,
        actor_role=account.role.value,
    )
    return TwoFactorRegenerateResponse(recovery_codes=codes)


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
    notifications: NotificationService = Depends(_notification_service),
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
    if revoked_count > 0:
        await _notify_owner_security_event(
            notifications,
            account,
            title="All other sessions signed out",
            message=f"{revoked_count} other active session(s) were signed out.",
        )
    return LogoutAllResponse(revoked_count=revoked_count)


@router.get("/sessions", response_model=AuthSessionListResponse)
async def list_sessions(
    request: Request,
    account: Account = Depends(get_current_account),
    service: AuthService = Depends(_service),
) -> AuthSessionListResponse:
    current_session_id = _bearer_session_id(request)
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
