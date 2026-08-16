import uuid
from typing import Any

from app.models.audit import AuditLog
from app.repositories.audit import AuditRepository


class AuditService:
    def __init__(self, audit_repository: AuditRepository):
        self._audit = audit_repository

    async def log_action(
        self,
        *,
        action: str,
        entity_type: str,
        actor_account_id: uuid.UUID | None = None,
        actor_role: str | None = None,
        entity_id: str | None = None,
        request_id: str | None = None,
        audit_metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        log_entry = AuditLog(
            action=action,
            entity_type=entity_type,
            actor_account_id=actor_account_id,
            actor_role=actor_role,
            entity_id=entity_id,
            request_id=request_id,
            audit_metadata=audit_metadata,
        )
        return await self._audit.create(log_entry)
