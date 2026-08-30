import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.models.account import Account
from app.models.payout import PayoutIntent
from app.repositories.audit import AuditRepository
from app.repositories.payout import PayoutRepository
from app.repositories.payout_security import PayoutSecurityRepository
from app.repositories.risk import RiskRepository
from app.schemas.payout import (
    LivePayoutReadinessOut,
    PayoutCommentCommand,
    PayoutDestinationInput,
    PayoutDestinationOut,
    PayoutIntentOut,
    PayoutListOut,
    PayoutManualCompleteCommand,
    PayoutNetworkOut,
    PayoutPolicyInput,
    PayoutPolicyOut,
    PayoutQueueCommand,
    PayoutReconcileCommand,
)
from app.services.audit import AuditService
from app.services.payout import (
    ControlledPayoutService,
    PayoutError,
    PayoutNotFoundError,
    PayoutPolicyService,
    PayoutSafetyError,
    mask_destination,
)
from app.services.payout_live.allowlist import PayoutAllowlistService
from app.services.payout_live.bybit import LivePayoutSecurityError
from app.services.payout_live.readiness import LivePayoutReadinessService
from app.services.payout_runtime import build_controlled_payout_service

router = APIRouter(
    prefix="/api/v1/owner",
    tags=["Owner Payouts"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _service(db: AsyncSession = Depends(get_db)) -> ControlledPayoutService:
    return build_controlled_payout_service(db)


def _repo(db: AsyncSession = Depends(get_db)) -> PayoutRepository:
    return PayoutRepository(db)


def _security_repo(db: AsyncSession = Depends(get_db)) -> PayoutSecurityRepository:
    return PayoutSecurityRepository(db)


def _allowlist(db: AsyncSession = Depends(get_db)) -> PayoutAllowlistService:
    return PayoutAllowlistService(PayoutSecurityRepository(db), AuditService(AuditRepository(db)))


def _external_mask(value: str | None) -> str | None:
    return mask_destination(value) if value else None


async def _out(
    intent: PayoutIntent, repo: PayoutRepository, *, detail: bool = False
) -> PayoutIntentOut:
    approvals = await repo.approvals(intent.id)
    events = await repo.events(intent.id) if detail else []
    return PayoutIntentOut(
        id=intent.id,
        withdrawal_id=intent.withdrawal_id,
        beneficiary_account_id=intent.beneficiary_account_id,
        asset=intent.asset,
        amount=intent.amount,
        network=intent.network,
        masked_destination=intent.masked_destination,
        fee_amount=intent.fee_amount,
        risk_policy_version=intent.risk_policy_version,
        risk_decision=intent.risk_decision,
        risk_reason=intent.risk_reason,
        treasury_generated_at=intent.treasury_generated_at,
        approval_policy_version=intent.approval_policy_version,
        required_approvals=intent.required_approvals,
        approval_count=sum(1 for item in approvals if item.decision == "approved"),
        provider_name=intent.provider_name,
        provider_mode=intent.provider_mode,
        status=intent.status,
        external_reference_masked=_external_mask(intent.external_reference),
        failure_kind=intent.failure_kind,
        failure_code=intent.failure_code,
        created_at=intent.created_at,
        approved_at=intent.approved_at,
        queued_at=intent.queued_at,
        execution_started_at=intent.execution_started_at,
        executed_at=intent.executed_at,
        reconciled_at=intent.reconciled_at,
        approvals=approvals,
        events=events,
    )


def _raise(exc: Exception) -> None:
    if isinstance(exc, PayoutNotFoundError):
        raise HTTPException(status_code=404, detail="payout not found") from exc
    code = exc.code if isinstance(exc, PayoutSafetyError) else str(exc)
    raise HTTPException(status_code=409, detail={"code": code}) from exc


@router.get("/payouts", response_model=PayoutListOut)
async def list_payouts(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: ControlledPayoutService = Depends(_service),
    repo: PayoutRepository = Depends(_repo),
) -> PayoutListOut:
    items, total = await service.list(status=status_filter, limit=limit, offset=offset)
    return PayoutListOut(
        items=[await _out(item, repo) for item in items], total=total, limit=limit, offset=offset
    )


@router.get("/payouts/{intent_id}", response_model=PayoutIntentOut)
async def get_payout(
    intent_id: uuid.UUID,
    service: ControlledPayoutService = Depends(_service),
    repo: PayoutRepository = Depends(_repo),
) -> PayoutIntentOut:
    try:
        return await _out(await service.get(intent_id), repo, detail=True)
    except PayoutError as exc:
        _raise(exc)


async def _command(
    intent_id: uuid.UUID,
    action: str,
    owner: Account,
    service: ControlledPayoutService,
    repo: PayoutRepository,
    payload=None,
) -> PayoutIntentOut:
    try:
        if action == "approve":
            intent = await service.approve(intent_id, owner, payload.comment if payload else None)
        elif action == "reject":
            intent = await service.reject(intent_id, owner, payload.comment if payload else None)
        elif action == "cancel":
            intent = await service.cancel(intent_id, owner, payload.comment if payload else None)
        elif action == "queue":
            intent = await service.queue(intent_id, owner, payload.outcome)
        elif action == "reconcile":
            intent = await service.reconcile(intent_id, owner, payload.outcome if payload else None)
        elif action == "manual":
            intent = await service.begin_manual(intent_id, owner)
        else:
            intent = await service.complete_manual(
                intent_id, owner, payload.external_reference, payload.evidence
            )
        return await _out(intent, repo, detail=True)
    except PayoutError as exc:
        _raise(exc)


@router.post("/payouts/{intent_id}/approve", response_model=PayoutIntentOut)
async def approve(
    intent_id: uuid.UUID,
    payload: PayoutCommentCommand | None = None,
    owner: Account = Depends(get_current_account),
    service: ControlledPayoutService = Depends(_service),
    repo: PayoutRepository = Depends(_repo),
):
    return await _command(intent_id, "approve", owner, service, repo, payload)


@router.post("/payouts/{intent_id}/reject", response_model=PayoutIntentOut)
async def reject(
    intent_id: uuid.UUID,
    payload: PayoutCommentCommand | None = None,
    owner: Account = Depends(get_current_account),
    service: ControlledPayoutService = Depends(_service),
    repo: PayoutRepository = Depends(_repo),
):
    return await _command(intent_id, "reject", owner, service, repo, payload)


@router.post("/payouts/{intent_id}/cancel", response_model=PayoutIntentOut)
async def cancel(
    intent_id: uuid.UUID,
    payload: PayoutCommentCommand | None = None,
    owner: Account = Depends(get_current_account),
    service: ControlledPayoutService = Depends(_service),
    repo: PayoutRepository = Depends(_repo),
):
    return await _command(intent_id, "cancel", owner, service, repo, payload)


@router.post("/payouts/{intent_id}/queue", response_model=PayoutIntentOut)
async def queue(
    intent_id: uuid.UUID,
    payload: PayoutQueueCommand,
    owner: Account = Depends(get_current_account),
    service: ControlledPayoutService = Depends(_service),
    repo: PayoutRepository = Depends(_repo),
):
    return await _command(intent_id, "queue", owner, service, repo, payload)


@router.post("/payouts/{intent_id}/reconcile", response_model=PayoutIntentOut)
async def reconcile(
    intent_id: uuid.UUID,
    payload: PayoutReconcileCommand | None = None,
    owner: Account = Depends(get_current_account),
    service: ControlledPayoutService = Depends(_service),
    repo: PayoutRepository = Depends(_repo),
):
    return await _command(intent_id, "reconcile", owner, service, repo, payload)


@router.post("/payouts/{intent_id}/manual", response_model=PayoutIntentOut)
async def begin_manual(
    intent_id: uuid.UUID,
    owner: Account = Depends(get_current_account),
    service: ControlledPayoutService = Depends(_service),
    repo: PayoutRepository = Depends(_repo),
):
    return await _command(intent_id, "manual", owner, service, repo)


@router.post("/payouts/{intent_id}/manual/complete", response_model=PayoutIntentOut)
async def complete_manual(
    intent_id: uuid.UUID,
    payload: PayoutManualCompleteCommand,
    owner: Account = Depends(get_current_account),
    service: ControlledPayoutService = Depends(_service),
    repo: PayoutRepository = Depends(_repo),
):
    return await _command(intent_id, "manual_complete", owner, service, repo, payload)


@router.post("/payouts/{intent_id}/execute")
async def execute_live_disabled(intent_id: uuid.UUID):
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail={"code": "LIVE_PAYOUT_NOT_AVAILABLE"}
    )


@router.get("/payout-policy", response_model=PayoutPolicyOut)
async def get_policy(repo: PayoutRepository = Depends(_repo)):
    return await repo.active_policy()


@router.post("/payout-policies", response_model=PayoutPolicyOut, status_code=201)
async def create_policy(
    payload: PayoutPolicyInput,
    owner: Account = Depends(get_current_account),
    repo: PayoutRepository = Depends(_repo),
):
    try:
        return await PayoutPolicyService(repo).create(owner, payload.model_dump())
    except PayoutError as exc:
        _raise(exc)


@router.post("/payout-policies/{policy_id}/activate", response_model=PayoutPolicyOut)
async def activate_policy(policy_id: uuid.UUID, repo: PayoutRepository = Depends(_repo)):
    try:
        return await PayoutPolicyService(repo).activate(policy_id)
    except PayoutError as exc:
        _raise(exc)


@router.get("/payout-readiness", response_model=LivePayoutReadinessOut)
async def live_readiness(
    security: PayoutSecurityRepository = Depends(_security_repo),
    payouts: PayoutRepository = Depends(_repo),
    db: AsyncSession = Depends(get_db),
):
    return await LivePayoutReadinessService(security, payouts, RiskRepository(db)).evaluate()


@router.get("/payout-addresses", response_model=list[PayoutDestinationOut])
async def payout_addresses(repo: PayoutSecurityRepository = Depends(_security_repo)):
    return await repo.destinations()


@router.post("/payout-addresses", response_model=PayoutDestinationOut, status_code=201)
async def create_payout_address(
    payload: PayoutDestinationInput,
    owner: Account = Depends(get_current_account),
    service: PayoutAllowlistService = Depends(_allowlist),
):
    try:
        return await service.create_destination(owner=owner, **payload.model_dump())
    except LivePayoutSecurityError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc


@router.post("/payout-addresses/{destination_id}/disable", response_model=PayoutDestinationOut)
async def disable_payout_address(
    destination_id: uuid.UUID,
    owner: Account = Depends(get_current_account),
    service: PayoutAllowlistService = Depends(_allowlist),
):
    try:
        return await service.disable_destination(destination_id, owner)
    except LivePayoutSecurityError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc


@router.get("/payout-networks", response_model=list[PayoutNetworkOut])
async def payout_networks(repo: PayoutSecurityRepository = Depends(_security_repo)):
    return await repo.networks()


@router.post("/payout-networks/{network_id}/disable", response_model=PayoutNetworkOut)
async def disable_payout_network(
    network_id: uuid.UUID,
    owner: Account = Depends(get_current_account),
    service: PayoutAllowlistService = Depends(_allowlist),
):
    try:
        return await service.disable_network(network_id, owner)
    except LivePayoutSecurityError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
