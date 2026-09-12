import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.core.url_safety import UnsafeWebhookURLError
from app.db.session import get_db
from app.enums.account import UserRole
from app.models.account import Account
from app.repositories.webhook import WebhookDeliveryRepository, WebhookRepository
from app.schemas.webhook import (
    WebhookCreate,
    WebhookCreated,
    WebhookDeliveryListResponse,
    WebhookListResponse,
    WebhookRead,
    WebhookUpdate,
)
from app.services.webhook import WebhookNotFoundError, WebhookService

router = APIRouter(
    prefix="/merchant/webhooks",
    tags=["Merchant Webhooks"],
    dependencies=[Depends(require_roles(UserRole.MERCHANT))],
)


def _service(db: AsyncSession = Depends(get_db)) -> WebhookService:
    return WebhookService(WebhookRepository(db), WebhookDeliveryRepository(db))


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="webhook not found")


def _unsafe_url(exc: UnsafeWebhookURLError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.post("", response_model=WebhookCreated, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    payload: WebhookCreate,
    merchant: Account = Depends(get_current_account),
    service: WebhookService = Depends(_service),
) -> WebhookCreated:
    try:
        webhook, secret = await service.create(
            merchant, url=payload.url, event_types=payload.event_types
        )
    except UnsafeWebhookURLError as exc:
        raise _unsafe_url(exc) from exc
    return WebhookCreated(**WebhookRead.model_validate(webhook).model_dump(), secret=secret)


@router.get("", response_model=WebhookListResponse)
async def list_webhooks(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    merchant: Account = Depends(get_current_account),
    service: WebhookService = Depends(_service),
) -> WebhookListResponse:
    items, total = await service.list_for_merchant(merchant.id, limit=limit, offset=offset)
    return WebhookListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{webhook_id}", response_model=WebhookRead)
async def get_webhook(
    webhook_id: uuid.UUID,
    merchant: Account = Depends(get_current_account),
    service: WebhookService = Depends(_service),
) -> WebhookRead:
    try:
        return await service.get_for_merchant(merchant.id, webhook_id)
    except WebhookNotFoundError as exc:
        raise _not_found() from exc


@router.patch("/{webhook_id}", response_model=WebhookRead)
async def update_webhook(
    webhook_id: uuid.UUID,
    payload: WebhookUpdate,
    merchant: Account = Depends(get_current_account),
    service: WebhookService = Depends(_service),
) -> WebhookRead:
    try:
        return await service.update(
            merchant.id,
            webhook_id,
            url=payload.url,
            status=payload.status,
            event_types=payload.event_types,
        )
    except WebhookNotFoundError as exc:
        raise _not_found() from exc
    except UnsafeWebhookURLError as exc:
        raise _unsafe_url(exc) from exc


@router.get("/{webhook_id}/deliveries", response_model=WebhookDeliveryListResponse)
async def list_webhook_deliveries(
    webhook_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    merchant: Account = Depends(get_current_account),
    service: WebhookService = Depends(_service),
) -> WebhookDeliveryListResponse:
    try:
        items, total = await service.list_deliveries_for_merchant(
            merchant.id, webhook_id, limit=limit, offset=offset
        )
    except WebhookNotFoundError as exc:
        raise _not_found() from exc
    return WebhookDeliveryListResponse(items=items, total=total, limit=limit, offset=offset)
