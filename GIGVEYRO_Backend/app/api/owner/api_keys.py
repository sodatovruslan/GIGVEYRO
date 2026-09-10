import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.repositories.api_key import ApiKeyRepository
from app.schemas.api_key import ApiKeyListResponse, ApiKeyRead
from app.services.api_key import ApiKeyAlreadyRevokedError, ApiKeyNotFoundError, ApiKeyService

router = APIRouter(
    prefix="/owner/api-keys",
    tags=["Owner API Management"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> ApiKeyService:
    return ApiKeyService(ApiKeyRepository(db))


@router.get("", response_model=ApiKeyListResponse)
async def list_api_keys(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: ApiKeyService = Depends(_service),
) -> ApiKeyListResponse:
    items, total = await service.list_all(limit=limit, offset=offset)
    return ApiKeyListResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("/{key_id}/revoke", response_model=ApiKeyRead)
async def revoke_api_key(
    key_id: uuid.UUID,
    service: ApiKeyService = Depends(_service),
) -> ApiKeyRead:
    try:
        return await service.revoke_as_owner(key_id)
    except ApiKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        ) from exc
    except ApiKeyAlreadyRevokedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
