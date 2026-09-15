import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.models.account import Account
from app.models.insurance_reserve import InsuranceReservePolicy
from app.repositories.audit import AuditRepository
from app.repositories.insurance_reserve import InsuranceReservePolicyRepository
from app.schemas.insurance_reserve import InsuranceReservePolicyInput, InsuranceReservePolicyOut
from app.services.audit import AuditService
from app.services.insurance_reserve import (
    InsuranceReservePolicyError,
    InsuranceReservePolicyNotFoundError,
    InsuranceReservePolicyService,
)

router = APIRouter(
    prefix="/api/v1/owner",
    tags=["Owner Insurance Reserve"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _repo(db: AsyncSession = Depends(get_db)) -> InsuranceReservePolicyRepository:
    return InsuranceReservePolicyRepository(db)


def _audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(AuditRepository(db))


def _policy_out(policy: InsuranceReservePolicy) -> InsuranceReservePolicyOut:
    return InsuranceReservePolicyOut.model_validate(policy, from_attributes=True)


@router.get("/insurance-reserve-policy", response_model=InsuranceReservePolicyOut)
async def get_policy(repo: InsuranceReservePolicyRepository = Depends(_repo)):
    return _policy_out(await repo.active_policy())


@router.post(
    "/insurance-reserve-policies", response_model=InsuranceReservePolicyOut, status_code=201
)
async def create_policy(
    payload: InsuranceReservePolicyInput,
    actor: Account = Depends(get_current_account),
    repo: InsuranceReservePolicyRepository = Depends(_repo),
    audit: AuditService = Depends(_audit_service),
):
    policy = await InsuranceReservePolicyService(repo).create(actor, payload.model_dump())
    await audit.log_action(
        action="insurance_reserve_policy.created",
        entity_type="insurance_reserve_policy",
        entity_id=str(policy.id),
        actor_account_id=actor.id,
        actor_role=actor.role.value,
        audit_metadata={
            "version": policy.version,
            "enabled": policy.enabled,
            "minimum_reserve_percentage": str(policy.minimum_reserve_percentage),
        },
    )
    return _policy_out(policy)


@router.post(
    "/insurance-reserve-policies/{policy_id}/activate", response_model=InsuranceReservePolicyOut
)
async def activate_policy(
    policy_id: uuid.UUID,
    actor: Account = Depends(get_current_account),
    repo: InsuranceReservePolicyRepository = Depends(_repo),
    audit: AuditService = Depends(_audit_service),
):
    try:
        policy = await InsuranceReservePolicyService(repo).activate(policy_id)
    except InsuranceReservePolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail="policy not found") from exc
    except InsuranceReservePolicyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await audit.log_action(
        action="insurance_reserve_policy.activated",
        entity_type="insurance_reserve_policy",
        entity_id=str(policy.id),
        actor_account_id=actor.id,
        actor_role=actor.role.value,
        audit_metadata={
            "version": policy.version,
            "enabled": policy.enabled,
            "minimum_reserve_percentage": str(policy.minimum_reserve_percentage),
        },
    )
    return _policy_out(policy)
