from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account
from app.db.session import get_db
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.schemas.account import AccountRead
from app.schemas.auth import LoginRequest, RefreshTokenRequest, TokenResponse
from app.services.auth import AuthenticationError, AuthService, TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(token_pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        access_expires_in=token_pair.access_expires_in,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    service = AuthService(AccountRepository(db))
    try:
        account = await service.authenticate(payload.username, payload.password)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
        ) from exc

    return _token_response(service.create_token_pair(account))


@router.get("/me", response_model=AccountRead)
async def read_current_account(account: Account = Depends(get_current_account)) -> Account:
    return account


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    payload: RefreshTokenRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    service = AuthService(AccountRepository(db))
    try:
        token_pair = await service.refresh(payload.refresh_token)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid refresh token",
        ) from exc

    return _token_response(token_pair)
