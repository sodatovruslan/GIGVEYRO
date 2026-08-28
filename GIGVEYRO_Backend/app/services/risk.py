import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from app.enums.risk import RiskDecision, RiskReason, RiskStatus
from app.models.account import Account
from app.models.risk import RiskPolicy, TreasurySnapshotRecord
from app.repositories.risk import RiskRepository

Q = Decimal("0.00000001")
BPS = Decimal("10000")


class RiskPolicyError(Exception):
    pass


class RiskBlockedError(Exception):
    def __init__(
        self,
        reason: RiskReason,
        current: Decimal | int | None,
        threshold: Decimal | int | None,
        policy_version: int,
    ):
        self.reason, self.current, self.threshold, self.policy_version = (
            reason,
            current,
            threshold,
            policy_version,
        )
        super().__init__(reason.value)


@dataclass(frozen=True, slots=True)
class TreasurySnapshot:
    generated_at: datetime
    external_observed_at: datetime | None
    provider_status: str
    external_bybit_usdt: Decimal
    external_bybit_usdc: Decimal
    internal_user_liability_usdt: Decimal
    merchant_liability_usdt: Decimal
    frozen_usdt: Decimal
    pending_withdrawal_usdt: Decimal
    open_deal_exposure_usdt: Decimal
    owner_profit_usdt: Decimal
    required_reserve_usdt: Decimal
    reserve_surplus_usdt: Decimal
    reserve_deficit_usdt: Decimal
    coverage_ratio_bps: int | None
    risk_status: RiskStatus
    policy_version: int
    data_age_seconds: int | None

    @property
    def total_internal_liability_usdt(self) -> Decimal:
        return self.internal_user_liability_usdt + self.merchant_liability_usdt


def calculate_snapshot(
    *,
    now: datetime,
    observed_at: datetime | None,
    provider_status: str,
    external_usdt: Decimal,
    external_usdc: Decimal,
    liabilities: dict[str, Decimal],
    policy: RiskPolicy,
) -> TreasurySnapshot:
    values = [external_usdt, external_usdc, *liabilities.values()]
    if any(not value.is_finite() or value < 0 for value in values):
        raise RiskPolicyError("Treasury values must be non-negative finite Decimals")
    total = liabilities["user"] + liabilities["merchant"]
    required = (total * Decimal(policy.minimum_reserve_ratio_bps) / BPS).quantize(
        Q, rounding=ROUND_HALF_UP
    )
    surplus = max(external_usdt - required, Decimal("0")).quantize(Q)
    deficit = max(required - external_usdt, Decimal("0")).quantize(Q)
    age = max(0, int((now - observed_at).total_seconds())) if observed_at else None
    fresh = (
        provider_status == "connected"
        and age is not None
        and age <= policy.max_treasury_data_age_seconds
    )
    coverage = (
        None
        if total == 0
        else int((external_usdt * BPS / total).to_integral_value(rounding=ROUND_HALF_UP))
    )
    if not fresh:
        status = RiskStatus.STALE if observed_at else RiskStatus.UNKNOWN
    elif total > 0 and external_usdt < required:
        status = RiskStatus.CRITICAL
    elif total == 0 or (coverage is not None and coverage >= policy.warning_reserve_ratio_bps):
        status = RiskStatus.HEALTHY
    elif coverage is not None and coverage >= policy.minimum_reserve_ratio_bps:
        status = RiskStatus.WARNING
    else:
        status = RiskStatus.CRITICAL
    return TreasurySnapshot(
        now,
        observed_at,
        provider_status,
        external_usdt.quantize(Q),
        external_usdc.quantize(Q),
        liabilities["user"].quantize(Q),
        liabilities["merchant"].quantize(Q),
        liabilities["frozen"].quantize(Q),
        liabilities["pending"].quantize(Q),
        liabilities["open_deals"].quantize(Q),
        liabilities["profit"].quantize(Q),
        required,
        surplus,
        deficit,
        coverage,
        status,
        policy.version,
        age,
    )


class TreasurySnapshotService:
    def __init__(self, repository: RiskRepository) -> None:
        self.repo = repository

    async def current(self, policy: RiskPolicy | None = None) -> TreasurySnapshot:
        policy = policy or await self.repo.active_policy()
        latest = await self.repo.latest_snapshot()
        return calculate_snapshot(
            now=datetime.now(UTC),
            observed_at=latest.external_observed_at if latest else None,
            provider_status=latest.provider_status if latest else "unknown",
            external_usdt=latest.external_bybit_usdt if latest else Decimal("0"),
            external_usdc=latest.external_bybit_usdc if latest else Decimal("0"),
            liabilities=await self.repo.liabilities(),
            policy=policy,
        )

    async def record(
        self, *, provider_status: str, observed_at: datetime | None, usdt: Decimal, usdc: Decimal
    ) -> TreasurySnapshot:
        snapshot = calculate_snapshot(
            now=datetime.now(UTC),
            observed_at=observed_at,
            provider_status=provider_status,
            external_usdt=usdt,
            external_usdc=usdc,
            liabilities=await self.repo.liabilities(),
            policy=await self.repo.active_policy(),
        )
        await self.repo.add_snapshot(
            TreasurySnapshotRecord(
                **{
                    name: getattr(snapshot, name)
                    for name in TreasurySnapshotRecord.__table__.columns.keys()
                    if name not in {"id", "generated_at", "data_age_seconds"}
                    and hasattr(snapshot, name)
                }
            )
        )
        return snapshot


class RiskDecisionService:
    @staticmethod
    def reserve(
        snapshot: TreasurySnapshot, policy: RiskPolicy
    ) -> tuple[RiskDecision, RiskReason | None]:
        if not policy.reserve_coverage_enabled:
            return RiskDecision.ALLOW, None
        if snapshot.risk_status in (RiskStatus.STALE, RiskStatus.UNKNOWN):
            return RiskDecision.BLOCK, RiskReason.RESERVE_DATA_STALE
        if snapshot.reserve_deficit_usdt > 0:
            return RiskDecision.BLOCK, RiskReason.INSUFFICIENT_RESERVE
        if policy.minimum_external_reserve_enabled and snapshot.external_bybit_usdt < (
            policy.minimum_external_usdt_reserve or 0
        ):
            return RiskDecision.BLOCK, RiskReason.MINIMUM_EXTERNAL_RESERVE
        return (
            (RiskDecision.WARN, None)
            if snapshot.risk_status == RiskStatus.WARNING
            else (RiskDecision.ALLOW, None)
        )


class RiskGuard:
    def __init__(self, repository: RiskRepository) -> None:
        self.repo = repository
        self.treasury = TreasurySnapshotService(repository)

    async def check_deal(self, user_id: uuid.UUID, amount: Decimal) -> None:
        await self.repo.serialize_enforcement()
        policy = await self.repo.active_policy(lock=True)
        snapshot = await self.treasury.current(policy)
        decision, reason = RiskDecisionService.reserve(snapshot, policy)
        if decision == RiskDecision.BLOCK:
            raise RiskBlockedError(
                reason,
                snapshot.coverage_ratio_bps,
                policy.minimum_reserve_ratio_bps,
                policy.version,
            )
        checks = [
            (
                policy.single_deal_enabled,
                amount,
                policy.max_single_deal_usdt,
                RiskReason.SINGLE_DEAL_LIMIT,
            ),
            (
                policy.user_exposure_enabled,
                await self.repo.user_frozen(user_id) + amount,
                policy.max_user_exposure_usdt,
                RiskReason.USER_EXPOSURE_LIMIT,
            ),
            (
                policy.total_open_deals_enabled,
                snapshot.open_deal_exposure_usdt + amount,
                policy.max_total_open_deals_usdt,
                RiskReason.TOTAL_OPEN_EXPOSURE_LIMIT,
            ),
        ]
        self._limits(checks, policy.version)

    async def check_withdrawal(self, amount: Decimal) -> None:
        await self.repo.serialize_enforcement()
        policy = await self.repo.active_policy(lock=True)
        snapshot = await self.treasury.current(policy)
        decision, reason = RiskDecisionService.reserve(snapshot, policy)
        if decision == RiskDecision.BLOCK:
            raise RiskBlockedError(
                reason,
                snapshot.coverage_ratio_bps,
                policy.minimum_reserve_ratio_bps,
                policy.version,
            )
        self._limits(
            [
                (
                    policy.pending_withdrawals_enabled,
                    snapshot.pending_withdrawal_usdt + amount,
                    policy.max_pending_withdrawals_usdt,
                    RiskReason.PENDING_WITHDRAWAL_LIMIT,
                )
            ],
            policy.version,
        )

    @staticmethod
    def _limits(checks, version: int) -> None:
        for enabled, current, threshold, reason in checks:
            if enabled and threshold is not None and current > threshold:
                raise RiskBlockedError(reason, current, threshold, version)


class RiskPolicyService:
    def __init__(self, repo: RiskRepository) -> None:
        self.repo = repo

    async def create(self, actor: Account, values: dict) -> RiskPolicy:
        policies = await self.repo.lock_policies()
        self.validate(values)
        return await self.repo.save_policy(
            RiskPolicy(
                version=max((p.version for p in policies), default=0) + 1,
                status="draft",
                created_by_account_id=actor.id,
                **values,
            )
        )

    async def activate(self, policy_id: uuid.UUID) -> RiskPolicy:
        policies = await self.repo.lock_policies()
        target = next((p for p in policies if p.id == policy_id), None)
        if not target:
            raise RiskPolicyError("Risk policy not found")
        if target.status == "active":
            return target
        if target.status != "draft":
            raise RiskPolicyError("Only draft policy can be activated")
        now = datetime.now(UTC)
        for policy in policies:
            if policy.status == "active":
                policy.status = "retired"
        await self.repo.session.flush()
        target.status, target.effective_from, target.activated_at = "active", now, now
        return await self.repo.save_policy(target)

    @staticmethod
    def validate(values: dict) -> None:
        if (
            not 0
            <= values["minimum_reserve_ratio_bps"]
            <= values["warning_reserve_ratio_bps"]
            <= 50000
        ):
            raise RiskPolicyError("Reserve ratios are invalid")
        for key, value in values.items():
            if isinstance(value, Decimal) and (not value.is_finite() or value < 0):
                raise RiskPolicyError(f"{key} must be a non-negative finite Decimal")
        pairs = (
            ("single_deal_enabled", "max_single_deal_usdt"),
            ("user_exposure_enabled", "max_user_exposure_usdt"),
            ("pending_withdrawals_enabled", "max_pending_withdrawals_usdt"),
            ("total_open_deals_enabled", "max_total_open_deals_usdt"),
            ("minimum_external_reserve_enabled", "minimum_external_usdt_reserve"),
        )
        for enabled, threshold in pairs:
            if values[enabled] and values[threshold] is None:
                raise RiskPolicyError(f"{threshold} is required when enabled")
