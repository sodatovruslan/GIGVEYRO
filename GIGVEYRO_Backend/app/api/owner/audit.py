import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.models.account import Account
from app.repositories.audit import AuditRepository

router = APIRouter(prefix="/api/v1/owner/audit-logs", tags=["Owner Audit Logs"])


@router.get("")
async def list_audit_logs(
    current_account: Annotated[Account, Depends(require_roles(UserRole.OWNER))],
    actor_account_id: uuid.UUID | None = None,
    action: str | None = None,
    entity_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    repo = AuditRepository(db)
    items = await repo.list_logs(
        actor_account_id=actor_account_id,
        action=action,
        entity_type=entity_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    total = await repo.count_logs(
        actor_account_id=actor_account_id,
        action=action,
        entity_type=entity_type,
        date_from=date_from,
        date_to=date_to,
    )
    return {
        "items": [
            {
                "id": str(item.id),
                "actor_account_id": str(item.actor_account_id) if item.actor_account_id else None,
                "actor_role": item.actor_role,
                "action": item.action,
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "request_id": item.request_id,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
