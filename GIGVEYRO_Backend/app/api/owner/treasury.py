import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account, require_roles
from app.db.session import get_db
from app.enums.account import UserRole
from app.enums.notification import NotificationMessageKey, NotificationType
from app.enums.risk import RiskStatus
from app.models.account import Account
from app.models.risk import RiskPolicy
from app.repositories.audit import AuditRepository
from app.repositories.notification import NotificationRepository
from app.repositories.risk import RiskRepository
from app.repositories.telegram import TelegramLinkRepository
from app.schemas.risk import (
    RiskPolicyInput,
    RiskPolicyOut,
    RiskPreviewOut,
    TreasuryHistoryOut,
    TreasurySummaryOut,
)
from app.services.audit import AuditService
from app.services.exchange_private.runtime import get_bybit_private_diagnostics
from app.services.notification import NotificationService
from app.services.risk import (
    RiskDecisionService,
    RiskPolicyError,
    RiskPolicyService,
    TreasurySnapshot,
    TreasurySnapshotService,
)
from app.services.telegram_provider import MockTelegramProvider

router = APIRouter(
    prefix="/api/v1/owner",
    tags=["Owner Treasury and Risk"],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)


def _repo(db: AsyncSession = Depends(get_db)) -> RiskRepository:
    return RiskRepository(db)


def _policy_out(policy: RiskPolicy) -> RiskPolicyOut:
    return RiskPolicyOut.model_validate(policy, from_attributes=True)


def _summary(value: TreasurySnapshot) -> TreasurySummaryOut:
    return TreasurySummaryOut(
        **{
            key: getattr(value, key)
            for key in TreasurySummaryOut.model_fields
            if hasattr(value, key)
            and key
            not in {
                "risk_status",
                "total_internal_liability_usdt",
                "available_reserve_usdt",
            }
        },
        total_external_stable_reserve=None,
        total_internal_liability_usdt=value.total_internal_liability_usdt,
        available_reserve_usdt=value.external_bybit_usdt,
        risk_status=value.risk_status.value,
    )


@router.get("/treasury/summary", response_model=TreasurySummaryOut)
async def summary(repo: RiskRepository = Depends(_repo)):
    return _summary(await TreasurySnapshotService(repo).current())


@router.post("/treasury/refresh", response_model=TreasurySummaryOut)
async def refresh(
    account: Account = Depends(get_current_account),
    repo: RiskRepository = Depends(_repo),
):
    previous = await repo.latest_snapshot()
    diagnostics = await get_bybit_private_diagnostics()
    balances = {
        item["asset"]: Decimal(
            item["available_balance"]
            if item["available_balance"] is not None
            else item["wallet_balance"]
        )
        for item in diagnostics.get("balances", [])
    }
    observed = max(
        (datetime.fromisoformat(item["received_at"]) for item in diagnostics.get("balances", [])),
        default=None,
    )
    snapshot = await TreasurySnapshotService(repo).record(
        provider_status=diagnostics.get("status", "unknown"),
        observed_at=observed,
        usdt=balances.get("USDT", Decimal("0")),
        usdc=balances.get("USDC", Decimal("0")),
    )
    previous_status = previous.risk_status if previous else None
    alert_statuses = {RiskStatus.WARNING, RiskStatus.CRITICAL, RiskStatus.STALE}
    if snapshot.risk_status in alert_statuses and snapshot.risk_status != previous_status:
        notifications = NotificationService(
            NotificationRepository(repo.session),
            TelegramLinkRepository(repo.session),
            MockTelegramProvider(),
        )
        message_key = {
            RiskStatus.WARNING: NotificationMessageKey.TREASURY_WARNING,
            RiskStatus.CRITICAL: NotificationMessageKey.TREASURY_CRITICAL,
            RiskStatus.STALE: NotificationMessageKey.TREASURY_STALE,
        }[snapshot.risk_status]
        await notifications.emit_semantic_notification(
            account.id,
            NotificationType.TREASURY_RISK_CHANGED,
            message_key,
            message_params={"risk_status": snapshot.risk_status.value},
            payload={"risk_status": snapshot.risk_status.value},
            dedupe_key=(
                f"treasury-risk:{previous.id if previous else 'initial'}:"
                f"{snapshot.risk_status.value}"
            ),
        )
    return _summary(snapshot)


@router.get("/treasury/history", response_model=TreasuryHistoryOut)
async def history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: RiskRepository = Depends(_repo),
):
    items, total = await repo.history(limit, offset)
    output = []
    for item in items:
        output.append(
            TreasurySummaryOut(
                generated_at=item.generated_at,
                external_observed_at=item.external_observed_at,
                data_age_seconds=max(
                    0, int((item.generated_at - item.external_observed_at).total_seconds())
                )
                if item.external_observed_at
                else None,
                provider_status=item.provider_status,
                external_bybit_usdt=item.external_bybit_usdt,
                external_bybit_usdc=item.external_bybit_usdc,
                total_external_stable_reserve=None,
                internal_user_liability_usdt=item.internal_user_liability_usdt,
                merchant_liability_usdt=item.merchant_liability_usdt,
                total_internal_liability_usdt=item.internal_user_liability_usdt
                + item.merchant_liability_usdt,
                frozen_usdt=item.frozen_usdt,
                pending_withdrawal_usdt=item.pending_withdrawal_usdt,
                open_deal_exposure_usdt=item.open_deal_exposure_usdt,
                owner_profit_usdt=item.owner_profit_usdt,
                required_reserve_usdt=item.required_reserve_usdt,
                available_reserve_usdt=item.external_bybit_usdt,
                reserve_surplus_usdt=item.reserve_surplus_usdt,
                reserve_deficit_usdt=item.reserve_deficit_usdt,
                coverage_ratio_bps=item.coverage_ratio_bps,
                risk_status=item.risk_status,
                policy_version=item.policy_version,
            )
        )
    return TreasuryHistoryOut(items=output, total=total, limit=limit, offset=offset)


@router.get("/risk/policy", response_model=RiskPolicyOut)
async def active_policy(repo: RiskRepository = Depends(_repo)):
    return _policy_out(await repo.active_policy())


@router.post("/risk/policies", response_model=RiskPolicyOut, status_code=201)
async def create_policy(
    payload: RiskPolicyInput,
    actor: Account = Depends(get_current_account),
    repo: RiskRepository = Depends(_repo),
):
    try:
        policy = await RiskPolicyService(repo).create(actor, payload.model_dump())
    except RiskPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await AuditService(AuditRepository(repo.session)).log_action(
        action="risk_policy.created",
        entity_type="risk_policy",
        entity_id=str(policy.id),
        actor_account_id=actor.id,
        actor_role=actor.role.value,
        audit_metadata={"version": policy.version, "config": payload.model_dump(mode="json")},
    )
    return _policy_out(policy)


@router.post("/risk/policies/{policy_id}/activate", response_model=RiskPolicyOut)
async def activate_policy(
    policy_id: uuid.UUID,
    actor: Account = Depends(get_current_account),
    repo: RiskRepository = Depends(_repo),
):
    current = await repo.active_policy()
    if current.id == policy_id:
        return _policy_out(current)
    try:
        policy = await RiskPolicyService(repo).activate(policy_id)
    except RiskPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await AuditService(AuditRepository(repo.session)).log_action(
        action="risk_policy.activated",
        entity_type="risk_policy",
        entity_id=str(policy.id),
        actor_account_id=actor.id,
        actor_role=actor.role.value,
        audit_metadata={"before_version": current.version, "after_version": policy.version},
    )
    controls = (
        "reserve_coverage_enabled",
        "single_deal_enabled",
        "user_exposure_enabled",
        "pending_withdrawals_enabled",
        "total_open_deals_enabled",
        "minimum_external_reserve_enabled",
    )
    audit = AuditService(AuditRepository(repo.session))
    for control in controls:
        if getattr(current, control) and not getattr(policy, control):
            await audit.log_action(
                action="risk_policy.disabled",
                entity_type="risk_policy",
                entity_id=str(policy.id),
                actor_account_id=actor.id,
                actor_role=actor.role.value,
                audit_metadata={"version": policy.version, "control": control},
            )
    return _policy_out(policy)


@router.post("/risk/preview", response_model=RiskPreviewOut)
async def preview(payload: RiskPolicyInput, repo: RiskRepository = Depends(_repo)):
    values = payload.model_dump()
    RiskPolicyService.validate(values)
    active = await repo.active_policy()
    draft = RiskPolicy(
        id=active.id,
        version=active.version + 1,
        status="draft",
        created_by_account_id=None,
        **values,
    )
    snapshot = await TreasurySnapshotService(repo).current(draft)
    decision, reason = RiskDecisionService.reserve(snapshot, draft)
    return RiskPreviewOut(
        snapshot=_summary(snapshot),
        reserve_decision=decision.value,
        reason_code=reason.value if reason else None,
    )
