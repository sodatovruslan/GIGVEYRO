import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.models.account import Account
from app.repositories.api_key import ApiKeyRepository
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyListResponse, ApiKeyRead
from app.services.api_key import ApiKeyAlreadyRevokedError, ApiKeyNotFoundError, ApiKeyService

router = APIRouter(
    prefix="/merchant/api-keys",
    tags=["Merchant API Keys"],
    dependencies=[Depends(require_roles(UserRole.MERCHANT))],
)


def _service(db: AsyncSession = Depends(get_db)) -> ApiKeyService:
    return ApiKeyService(ApiKeyRepository(db))


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate,
    merchant: Account = Depends(get_current_account),
    service: ApiKeyService = Depends(_service),
) -> ApiKeyCreated:
    api_key, raw_key = await service.create(merchant, label=payload.label)
    return ApiKeyCreated(**ApiKeyRead.model_validate(api_key).model_dump(), raw_key=raw_key)


@router.get("", response_model=ApiKeyListResponse)
async def list_api_keys(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    merchant: Account = Depends(get_current_account),
    service: ApiKeyService = Depends(_service),
) -> ApiKeyListResponse:
    items, total = await service.list_for_merchant(merchant.id, limit=limit, offset=offset)
    return ApiKeyListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/{key_id}/revoke", response_model=ApiKeyRead)
async def revoke_api_key(
    key_id: uuid.UUID,
    merchant: Account = Depends(get_current_account),
    service: ApiKeyService = Depends(_service),
) -> ApiKeyRead:
    try:
        return await service.revoke(merchant.id, key_id)
    except ApiKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        ) from exc
    except ApiKeyAlreadyRevokedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
