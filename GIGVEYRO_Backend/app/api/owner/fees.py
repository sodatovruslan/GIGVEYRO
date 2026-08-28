import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.fees import FeeType
from app.enums.wallet import Currency
from app.models.account import Account
from app.models.fees import FeePolicy
from app.repositories.audit import AuditRepository
from app.repositories.fees import FeeRepository
from app.schemas.fees import (
    FeeComponentOut,
    FeePolicyCreate,
    FeePolicyOut,
    FeePreviewOut,
    FeePreviewRequest,
    ProfitEntriesOut,
    ProfitEntryOut,
    ProfitSummaryOut,
)
from app.services.audit import AuditService
from app.services.fees import (
    ENFORCED_FEE_TYPES,
    FeeCalculator,
    FeePolicyNotFoundError,
    FeePolicyService,
    FeePolicyValidationError,
    FeeTerms,
    component_terms,
    policy_component,
)

router = APIRouter(
    tags=["Owner Fees and Profit"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> FeePolicyService:
    return FeePolicyService(FeeRepository(db))


def _policy_out(policy: FeePolicy) -> FeePolicyOut:
    return FeePolicyOut(
        id=policy.id,
        version=policy.version,
        status=policy.status,
        effective_from=policy.effective_from,
        created_at=policy.created_at,
        activated_at=policy.activated_at,
        components=[
            FeeComponentOut(
                fee_type=component.fee_type,
                enabled=component.enabled,
                percent_bps=component.percent_bps,
                fixed_fee=component.fixed_fee,
                min_fee=component.min_fee,
                max_fee=component.max_fee,
                payer=component.payer,
                supported_for_charging=FeeType(component.fee_type) in ENFORCED_FEE_TYPES,
            )
            for component in sorted(policy.components, key=lambda item: item.fee_type)
        ],
    )


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, FeePolicyNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fee policy not found")
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


@router.get("/api/v1/owner/fees/policy", response_model=FeePolicyOut)
async def active_policy(service: FeePolicyService = Depends(_service)) -> FeePolicyOut:
    return _policy_out(await service.active())


@router.post(
    "/api/v1/owner/fees/policies",
    response_model=FeePolicyOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_policy(
    payload: FeePolicyCreate,
    actor: Account = Depends(get_current_account),
    service: FeePolicyService = Depends(_service),
    db: AsyncSession = Depends(get_db),
) -> FeePolicyOut:
    try:
        policy = await service.create(
            actor,
            {
                fee_type: FeeTerms(
                    enabled=value.enabled,
                    percent_bps=value.percent_bps,
                    fixed_fee=value.fixed_fee,
                    min_fee=value.min_fee,
                    max_fee=value.max_fee,
                    payer=value.payer.value if value.payer else None,
                )
                for fee_type, value in payload.components.items()
            },
        )
    except FeePolicyValidationError as exc:
        raise _error(exc) from exc
    await AuditService(AuditRepository(db)).log_action(
        action="fee_policy.created",
        entity_type="fee_policy",
        entity_id=str(policy.id),
        actor_account_id=actor.id,
        actor_role=actor.role.value,
        audit_metadata={"version": policy.version, "components": _safe_components(policy)},
    )
    return _policy_out(policy)


@router.post("/api/v1/owner/fees/policies/{policy_id}/activate", response_model=FeePolicyOut)
async def activate_policy(
    policy_id: uuid.UUID,
    actor: Account = Depends(get_current_account),
    service: FeePolicyService = Depends(_service),
    db: AsyncSession = Depends(get_db),
) -> FeePolicyOut:
    previous = await service.active()
    if previous.id == policy_id:
        return _policy_out(previous)
    try:
        policy = await service.activate(actor, policy_id)
    except (FeePolicyNotFoundError, FeePolicyValidationError) as exc:
        raise _error(exc) from exc
    audit = AuditService(AuditRepository(db))
    await audit.log_action(
        action="fee_policy.activated",
        entity_type="fee_policy",
        entity_id=str(policy.id),
        actor_account_id=actor.id,
        actor_role=actor.role.value,
        audit_metadata={
            "before_version": previous.version,
            "after_version": policy.version,
            "components": _safe_components(policy),
        },
    )
    previous_enabled = {item.fee_type for item in previous.components if item.enabled}
    current_enabled = {item.fee_type for item in policy.components if item.enabled}
    for fee_type in sorted(previous_enabled - current_enabled):
        await audit.log_action(
            action="fee_policy.disabled",
            entity_type="fee_policy_component",
            entity_id=str(policy.id),
            actor_account_id=actor.id,
            actor_role=actor.role.value,
            audit_metadata={"version": policy.version, "fee_component": fee_type},
        )
    return _policy_out(policy)


@router.post("/api/v1/owner/fees/preview", response_model=FeePreviewOut)
async def preview_fee(
    payload: FeePreviewRequest,
    service: FeePolicyService = Depends(_service),
) -> FeePreviewOut:
    try:
        policy = (
            await service.policy(payload.policy_id)
            if payload.policy_id is not None
            else await service.active()
        )
    except FeePolicyNotFoundError as exc:
        raise _error(exc) from exc
    component = policy_component(policy, payload.fee_type)
    try:
        result = FeeCalculator.calculate(payload.amount, component_terms(component))
    except FeePolicyValidationError as exc:
        raise _error(exc) from exc
    return FeePreviewOut(
        policy_version=policy.version,
        fee_type=payload.fee_type,
        currency=payload.currency,
        gross=result.gross,
        percent_fee=result.percent_fee,
        fixed_fee=result.fixed_fee,
        total_fee=result.total_fee,
        net=result.net,
    )


@router.get("/api/v1/owner/profit/summary", response_model=ProfitSummaryOut)
async def profit_summary(service: FeePolicyService = Depends(_service)) -> ProfitSummaryOut:
    return ProfitSummaryOut(periods=await service.summary())


@router.get("/api/v1/owner/profit/entries", response_model=ProfitEntriesOut)
async def profit_entries(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    fee_type: FeeType | None = None,
    currency: Currency | None = None,
    source_type: str | None = Query(default=None, max_length=40),
    source_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> ProfitEntriesOut:
    items, total = await FeeRepository(db).list_profit_entries(
        date_from=date_from,
        date_to=date_to,
        fee_type=fee_type.value if fee_type else None,
        currency=currency.value if currency else None,
        source_type=source_type,
        source_id=source_id,
        limit=limit,
        offset=offset,
    )
    return ProfitEntriesOut(
        items=[ProfitEntryOut.model_validate(item, from_attributes=True) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def _safe_components(policy: FeePolicy) -> list[dict]:
    return [
        {
            "fee_type": item.fee_type,
            "enabled": item.enabled,
            "percent_bps": item.percent_bps,
            "fixed_fee": str(item.fixed_fee),
            "min_fee": str(item.min_fee) if item.min_fee is not None else None,
            "max_fee": str(item.max_fee) if item.max_fee is not None else None,
            "payer": item.payer,
        }
        for item in policy.components
    ]
