import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.core.config import settings
from app.enums.account import UserRole
from app.enums.notification import NotificationMessageKey, NotificationType
from app.enums.payout import (
    PayoutApprovalDecision,
    PayoutFailureKind,
    PayoutProviderMode,
    PayoutProviderResult,
    PayoutSimulationOutcome,
    PayoutStatus,
)
from app.enums.risk import RiskDecision, RiskReason, RiskStatus
from app.enums.withdrawal import WithdrawalDestinationType, WithdrawalStatus
from app.infra.redis_rate_limiter import RedisRateLimiter
from app.models.account import Account
from app.models.payout import PayoutApproval, PayoutIntent, PayoutPolicy
from app.models.withdrawal import MerchantWithdrawal
from app.repositories.account import AccountRepository
from app.repositories.payout import PayoutRepository
from app.repositories.payout_security import PayoutSecurityRepository
from app.repositories.risk import RiskRepository
from app.repositories.withdrawal import WithdrawalRepository
from app.services.audit import AuditService
from app.services.notification import NotificationService
from app.services.payout_live.allowlist import PayoutAllowlistService
from app.services.payout_live.bybit import BybitLivePayoutProvider, destination_fingerprint
from app.services.payout_live.readiness import LivePayoutReadinessService
from app.services.payout_provider import (
    DisabledPayoutProvider,
    ExchangePayoutProvider,
    SimulatedPayoutProvider,
)
from app.services.realtime import RealtimeEventService
from app.services.risk import RiskDecisionService, TreasurySnapshotService
from app.services.wallet import WalletService
from app.services.withdrawal import transition_withdrawal

# One live Bybit withdrawal-create attempt per coin/chain per this many
# seconds - matches Bybit's own documented secondary rate limit and prevents
# two workers from racing a live withdrawal for the same asset/network.
_BYBIT_WITHDRAW_COOLDOWN_SECONDS = 10


class PayoutError(Exception):
    pass


class PayoutNotFoundError(PayoutError):
    pass


class PayoutTransitionError(PayoutError):
    pass


class PayoutSafetyError(PayoutError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


ALLOWED_TRANSITIONS: dict[PayoutStatus, set[PayoutStatus]] = {
    PayoutStatus.REQUESTED: {PayoutStatus.RISK_REVIEW, PayoutStatus.CANCELLED},
    PayoutStatus.RISK_REVIEW: {
        PayoutStatus.APPROVED,
        PayoutStatus.REJECTED,
        PayoutStatus.CANCELLED,
    },
    PayoutStatus.APPROVED: {
        PayoutStatus.QUEUED,
        PayoutStatus.AWAITING_MANUAL_SETTLEMENT,
        PayoutStatus.CANCELLED,
    },
    PayoutStatus.QUEUED: {PayoutStatus.EXECUTION_PENDING, PayoutStatus.CANCELLED},
    PayoutStatus.EXECUTION_PENDING: {
        PayoutStatus.EXECUTING,
        PayoutStatus.SUCCEEDED,
        PayoutStatus.FAILED,
        PayoutStatus.RECONCILIATION_REQUIRED,
        PayoutStatus.CANCELLED,
    },
    PayoutStatus.EXECUTING: {
        PayoutStatus.SUCCEEDED,
        PayoutStatus.FAILED,
        PayoutStatus.EXECUTION_PENDING,
        PayoutStatus.RECONCILIATION_REQUIRED,
    },
    PayoutStatus.AWAITING_MANUAL_SETTLEMENT: {PayoutStatus.SUCCEEDED, PayoutStatus.CANCELLED},
    PayoutStatus.RECONCILIATION_REQUIRED: {
        PayoutStatus.SUCCEEDED,
        PayoutStatus.FAILED,
        PayoutStatus.EXECUTION_PENDING,
    },
    PayoutStatus.SUCCEEDED: set(),
    PayoutStatus.FAILED: set(),
    PayoutStatus.REJECTED: set(),
    PayoutStatus.CANCELLED: set(),
}


def transition_payout(intent: PayoutIntent, new_status: PayoutStatus) -> None:
    current = PayoutStatus(intent.status)
    if new_status not in ALLOWED_TRANSITIONS[current]:
        raise PayoutTransitionError(
            f"cannot transition payout from {current.value} to {new_status.value}"
        )
    intent.status = new_status.value
    now = datetime.now(UTC)
    if new_status == PayoutStatus.APPROVED:
        intent.approved_at = now
    elif new_status == PayoutStatus.QUEUED:
        intent.queued_at = now
    elif new_status == PayoutStatus.EXECUTING:
        intent.execution_started_at = now
    elif new_status in (PayoutStatus.SUCCEEDED, PayoutStatus.FAILED):
        intent.executed_at = now
    elif new_status == PayoutStatus.RECONCILIATION_REQUIRED:
        intent.reconciled_at = None


def mask_destination(value: str) -> str:
    return value if len(value) <= 8 else f"{value[:4]}…{value[-4:]}"


def intent_hash(intent: PayoutIntent) -> str:
    def money(value: Decimal) -> str:
        return format(Decimal(value).quantize(Decimal("0.00000001")), "f")

    payload = {
        "withdrawal_id": str(intent.withdrawal_id),
        "requester": str(intent.requester_account_id),
        "beneficiary": str(intent.beneficiary_account_id),
        "asset": intent.asset,
        "amount": money(intent.amount),
        "network": intent.network,
        "destination": intent.destination,
        "fee": money(intent.fee_amount),
        "risk_policy_version": intent.risk_policy_version,
        "risk_decision": intent.risk_decision,
        "risk_reason": intent.risk_reason,
        "treasury_generated_at": intent.treasury_generated_at.isoformat(),
        "approval_policy_version": intent.approval_policy_version,
        "required_approvals": intent.required_approvals,
        "provider_mode": intent.provider_mode,
        "idempotency_key": intent.idempotency_key,
    }
    if intent.provider_mode == PayoutProviderMode.LIVE.value:
        payload["provider"] = intent.provider_name
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class PayoutPolicyService:
    def __init__(self, repo: PayoutRepository) -> None:
        self.repo = repo

    async def create(self, actor: Account, values: dict) -> PayoutPolicy:
        if values.get("auto_approval_enabled"):
            raise PayoutSafetyError("AUTO_APPROVAL_NOT_AVAILABLE")
        policies = await self.repo.policies_for_update()
        self._validate(values)
        return await self.repo.save_policy(
            PayoutPolicy(
                version=max((p.version for p in policies), default=0) + 1,
                status="draft",
                created_by_account_id=actor.id,
                **values,
            )
        )

    async def activate(self, policy_id: uuid.UUID) -> PayoutPolicy:
        policies = await self.repo.policies_for_update()
        target = next((p for p in policies if p.id == policy_id), None)
        if target is None:
            raise PayoutNotFoundError()
        if target.status == "active":
            return target
        if target.status != "draft":
            raise PayoutTransitionError("only draft payout policy can be activated")
        for policy in policies:
            if policy.status == "active":
                policy.status = "retired"
        # Flush the retirement before activating the new version: the
        # partial unique index on status='active' is checked immediately
        # (not deferred), so both updates must never be visible to Postgres
        # as "active" at the same instant. (Same fix as
        # InsuranceReservePolicyService.activate / RiskPolicyService.activate.)
        await self.repo.session.flush()
        target.status = "active"
        target.activated_at = datetime.now(UTC)
        return await self.repo.save_policy(target)

    @staticmethod
    def _validate(values: dict) -> None:
        if values["default_required_approvals"] not in (1, 2) or values[
            "high_value_required_approvals"
        ] not in (1, 2):
            raise PayoutError("required approvals must be 1 or 2")
        pairs = (
            ("max_single_payout_enabled", "max_single_payout_usdt"),
            ("max_daily_payout_enabled", "max_daily_payout_usdt"),
            ("max_hourly_payout_enabled", "max_hourly_payout_usdt"),
            ("max_pending_payout_enabled", "max_pending_payout_usdt"),
            ("max_asset_exposure_enabled", "max_asset_exposure_usdt"),
        )
        for enabled, limit in pairs:
            value = values.get(limit)
            if values.get(enabled) and value is None:
                raise PayoutError(f"{limit} is required")
            if value is not None and (not value.is_finite() or value < 0):
                raise PayoutError(f"{limit} must be non-negative")


class ControlledPayoutService:
    def __init__(
        self,
        repo: PayoutRepository,
        withdrawals: WithdrawalRepository,
        risk_repo: RiskRepository,
        wallet: WalletService,
        accounts: AccountRepository,
        *,
        provider: ExchangePayoutProvider | None = None,
        audit: AuditService | None = None,
        notifications: NotificationService | None = None,
        realtime: RealtimeEventService | None = None,
        rate_limiter: RedisRateLimiter | None = None,
    ) -> None:
        self.repo = repo
        self.withdrawals = withdrawals
        self.risk_repo = risk_repo
        self.wallet = wallet
        self.accounts = accounts
        self.provider = provider or self._configured_provider(risk_repo)
        self.audit = audit
        self.notifications = notifications
        self.realtime = realtime
        self._rate_limiter = rate_limiter or RedisRateLimiter()

    @staticmethod
    def _configured_provider(risk_repo: RiskRepository) -> ExchangePayoutProvider:
        if settings.PAYOUT_PROVIDER_MODE == PayoutProviderMode.LIVE.value:
            return BybitLivePayoutProvider(risk_repository=risk_repo)
        if settings.PAYOUT_PROVIDER_MODE == PayoutProviderMode.SIMULATED.value:
            return SimulatedPayoutProvider()
        return DisabledPayoutProvider()

    async def create_for_withdrawal(self, withdrawal: MerchantWithdrawal) -> PayoutIntent:
        existing = await self.repo.by_withdrawal(withdrawal.id)
        if existing:
            return existing
        policy = await self.repo.active_policy()
        snapshot, decision, reason = await self._risk(execution=False)
        required = policy.default_required_approvals
        if (
            policy.dual_approval_threshold_usdt is not None
            and withdrawal.amount > policy.dual_approval_threshold_usdt
        ):
            required = policy.high_value_required_approvals
        network = (
            "TRC20"
            if withdrawal.destination_type == WithdrawalDestinationType.USDT_TRC20_ADDRESS
            else "BYBIT_UID"
        )
        # Live execution is scoped to USDT/TRC20 only (V1). A BYBIT_UID
        # withdrawal never becomes a live-provider intent, even when
        # PAYOUT_PROVIDER_MODE=live globally - it stays on the existing
        # manual-settlement path (begin_manual/complete_manual), unchanged.
        if settings.PAYOUT_PROVIDER_MODE == PayoutProviderMode.LIVE.value and network == "TRC20":
            provider_name, provider_mode = "bybit", PayoutProviderMode.LIVE.value
        elif settings.PAYOUT_PROVIDER_MODE == PayoutProviderMode.SIMULATED.value:
            provider_name, provider_mode = "simulator", PayoutProviderMode.SIMULATED.value
        else:
            provider_name, provider_mode = "disabled", PayoutProviderMode.DISABLED.value
        intent = PayoutIntent(
            withdrawal_id=withdrawal.id,
            requester_account_id=withdrawal.created_by_account_id,
            beneficiary_account_id=withdrawal.merchant_id,
            asset=withdrawal.currency.value.upper(),
            amount=withdrawal.amount,
            network=network,
            destination=withdrawal.destination,
            masked_destination=mask_destination(withdrawal.destination),
            fee_amount=Decimal("0"),
            risk_policy_version=snapshot.policy_version,
            risk_decision=decision.value,
            risk_reason=reason.value if reason else None,
            treasury_generated_at=snapshot.generated_at,
            approval_policy_version=policy.version,
            required_approvals=required,
            provider_name=provider_name,
            provider_mode=provider_mode,
            status=PayoutStatus.REQUESTED.value,
            idempotency_key=f"withdrawal:{withdrawal.id}",
            intent_hash="pending",
        )
        intent.intent_hash = intent_hash(intent)
        await self.repo.add_intent(intent)
        if network == "TRC20":
            await self._ensure_destination(intent)
        transition_payout(intent, PayoutStatus.RISK_REVIEW)
        await self.repo.save_intent(intent)
        await self._event(
            intent,
            "payout.intent_created",
            withdrawal.created_by_account_id,
            {
                "provider_mode": intent.provider_mode,
                "simulated": intent.provider_mode == "simulated",
            },
        )
        await self._notify_owner(
            intent, NotificationMessageKey.PAYOUT_APPROVAL_REQUIRED, "approval"
        )
        return intent

    async def _ensure_destination(self, intent: PayoutIntent) -> None:
        """Auto-register intent.destination as an approved PayoutDestination
        scoped to intent.beneficiary_account_id, so _live_gate has a real,
        per-transaction record to check later - not just "some destination
        exists somewhere". Idempotent: a repeat withdrawal to the same
        address by the same beneficiary reuses the existing row. Owner can
        still `disable_destination` this specific row later (e.g. on
        suspected fraud) even after the intent was created - _live_gate
        re-checks `enabled` fresh on every call, not just at creation."""
        beneficiary = await self.accounts.get_by_id(intent.beneficiary_account_id)
        if beneficiary is None:
            raise PayoutSafetyError("BENEFICIARY_NOT_FOUND")
        allowlist = PayoutAllowlistService(PayoutSecurityRepository(self.repo.session), self.audit)
        await allowlist.ensure_destination_for_beneficiary(
            beneficiary_account_id=intent.beneficiary_account_id,
            actor_role=beneficiary.role.value,
            label=f"Withdrawal {intent.withdrawal_id}",
            asset=intent.asset,
            network=intent.network,
            address=intent.destination,
        )

    async def approve(
        self, intent_id: uuid.UUID, owner: Account, comment: str | None = None
    ) -> PayoutIntent:
        intent = await self._intent(intent_id, lock=True)
        self._verify_hash(intent)
        existing = await self.repo.approval(intent.id, owner.id)
        if existing:
            if existing.decision == PayoutApprovalDecision.APPROVED.value:
                return intent
            raise PayoutTransitionError("approver already rejected this payout")
        if PayoutStatus(intent.status) != PayoutStatus.RISK_REVIEW:
            raise PayoutTransitionError("payout is not awaiting approval")
        snapshot, decision, reason = await self._risk(execution=False)
        if decision == RiskDecision.BLOCK:
            raise PayoutSafetyError(reason.value if reason else "RISK_BLOCKED")
        policy = await self.repo.active_policy()
        await self._limits(intent, policy)
        await self.repo.add_approval(
            PayoutApproval(
                payout_intent_id=intent.id,
                approver_account_id=owner.id,
                decision=PayoutApprovalDecision.APPROVED.value,
                intent_hash=intent.intent_hash,
                comment=comment,
            )
        )
        await self._event(
            intent,
            "payout.risk_checked",
            owner.id,
            {
                "decision": decision.value,
                "reason": reason.value if reason else None,
                "risk_policy_version": snapshot.policy_version,
                "treasury_generated_at": snapshot.generated_at.isoformat(),
            },
        )
        await self._event(intent, "payout.approved", owner.id, {"intent_hash": intent.intent_hash})
        if await self.repo.approval_count(intent.id) >= intent.required_approvals:
            withdrawal = await self.withdrawals.get_by_id_for_update(intent.withdrawal_id)
            if withdrawal is None:
                raise PayoutSafetyError("WITHDRAWAL_NOT_FOUND")
            if withdrawal.status == WithdrawalStatus.PENDING:
                transition_withdrawal(withdrawal, WithdrawalStatus.APPROVED, owner.id)
                await self.withdrawals.save(withdrawal)
            transition_payout(intent, PayoutStatus.APPROVED)
            await self.repo.save_intent(intent)
            await self._notify_merchant(
                intent,
                NotificationMessageKey.WITHDRAWAL_APPROVED,
                withdrawal.public_id,
                "approved",
            )
        return intent

    async def reject(
        self, intent_id: uuid.UUID, owner: Account, comment: str | None = None
    ) -> PayoutIntent:
        intent = await self._intent(intent_id, lock=True)
        self._verify_hash(intent)
        if PayoutStatus(intent.status) == PayoutStatus.REJECTED:
            return intent
        if PayoutStatus(intent.status) != PayoutStatus.RISK_REVIEW:
            raise PayoutTransitionError("payout is not awaiting approval")
        await self.repo.add_approval(
            PayoutApproval(
                payout_intent_id=intent.id,
                approver_account_id=owner.id,
                decision=PayoutApprovalDecision.REJECTED.value,
                intent_hash=intent.intent_hash,
                comment=comment,
            )
        )
        withdrawal = await self._withdrawal(intent)
        await self.wallet.release_for_withdrawal(
            merchant_id=withdrawal.merchant_id,
            amount=withdrawal.amount,
            withdrawal_id=withdrawal.id,
            actor_id=owner.id,
        )
        transition_withdrawal(withdrawal, WithdrawalStatus.REJECTED, owner.id)
        transition_payout(intent, PayoutStatus.REJECTED)
        await self.withdrawals.save(withdrawal)
        await self.repo.save_intent(intent)
        await self._event(intent, "payout.rejected", owner.id)
        await self._notify_merchant(
            intent,
            NotificationMessageKey.WITHDRAWAL_REJECTED,
            withdrawal.public_id,
            "rejected",
        )
        return intent

    async def cancel(
        self, intent_id: uuid.UUID, owner: Account, comment: str | None = None
    ) -> PayoutIntent:
        intent = await self._intent(intent_id, lock=True)
        self._verify_hash(intent)
        if PayoutStatus(intent.status) == PayoutStatus.CANCELLED:
            return intent
        if PayoutStatus(intent.status) not in (
            PayoutStatus.RISK_REVIEW,
            PayoutStatus.APPROVED,
            PayoutStatus.QUEUED,
            PayoutStatus.EXECUTION_PENDING,
            PayoutStatus.AWAITING_MANUAL_SETTLEMENT,
        ):
            raise PayoutTransitionError("payout cannot be cancelled after execution started")
        withdrawal = await self._withdrawal(intent)
        await self.wallet.release_for_withdrawal(
            merchant_id=withdrawal.merchant_id,
            amount=withdrawal.amount,
            withdrawal_id=withdrawal.id,
            actor_id=owner.id,
        )
        if withdrawal.status in (WithdrawalStatus.PENDING, WithdrawalStatus.APPROVED):
            transition_withdrawal(withdrawal, WithdrawalStatus.CANCELLED, owner.id)
        transition_payout(intent, PayoutStatus.CANCELLED)
        await self.withdrawals.save(withdrawal)
        await self.repo.save_intent(intent)
        await self._event(intent, "payout.cancelled", owner.id, {"comment": bool(comment)})
        return intent

    async def queue(
        self, intent_id: uuid.UUID, owner: Account, outcome: PayoutSimulationOutcome
    ) -> PayoutIntent:
        intent = await self._intent(intent_id, lock=True)
        self._verify_hash(intent)
        await self._execution_gate(intent, require_fresh=False)
        if PayoutStatus(intent.status) == PayoutStatus.QUEUED:
            return intent
        if PayoutStatus(intent.status) != PayoutStatus.APPROVED:
            raise PayoutTransitionError("only approved payout can be queued")
        intent.simulation_outcome = outcome.value
        transition_payout(intent, PayoutStatus.QUEUED)
        await self.repo.save_intent(intent)
        await self._event(
            intent, "payout.queued", owner.id, {"simulated": True, "outcome": outcome.value}
        )
        return intent

    async def execute(
        self, intent_id: uuid.UUID, actor_id: uuid.UUID | None = None
    ) -> PayoutIntent:
        intent = await self._intent(intent_id, lock=True)
        self._verify_hash(intent)
        if PayoutStatus(intent.status) in (
            PayoutStatus.SUCCEEDED,
            PayoutStatus.FAILED,
            PayoutStatus.RECONCILIATION_REQUIRED,
        ):
            return intent
        if PayoutStatus(intent.status) not in (
            PayoutStatus.QUEUED,
            PayoutStatus.EXECUTION_PENDING,
        ):
            raise PayoutTransitionError("payout is not execution pending")
        snapshot, decision, reason = await self._execution_gate(intent, require_fresh=True)
        if PayoutStatus(intent.status) == PayoutStatus.QUEUED:
            transition_payout(intent, PayoutStatus.EXECUTION_PENDING)
        await self._event(
            intent,
            "payout.risk_checked",
            actor_id,
            {
                "phase": "execution",
                "decision": decision.value,
                "reason": reason.value if reason else None,
                "risk_policy_version": snapshot.policy_version,
                "treasury_generated_at": snapshot.generated_at.isoformat(),
            },
        )
        transition_payout(intent, PayoutStatus.EXECUTING)
        await self._event(intent, "payout.execution_started", actor_id, {"simulated": True})
        result = await self.provider.execute(intent)
        intent.external_reference = intent.external_reference or result.external_reference
        if result.status == PayoutProviderResult.SUCCEEDED:
            await self._finalize(intent, actor_id)
            await self._event(intent, "payout.simulated_succeeded", actor_id, {"simulated": True})
        elif result.status == PayoutProviderResult.FAILED:
            intent.failure_kind = PayoutFailureKind.PERMANENT.value
            intent.failure_code = result.failure_code
            transition_payout(intent, PayoutStatus.FAILED)
            await self._event(
                intent,
                "payout.failed",
                actor_id,
                {"failure_kind": intent.failure_kind, "code": result.failure_code},
            )
            await self._notify_owner(
                intent, NotificationMessageKey.PAYOUT_EXECUTION_FAILED, "failed"
            )
        elif result.status == PayoutProviderResult.PENDING:
            intent.failure_kind = PayoutFailureKind.UNKNOWN.value
            intent.failure_code = result.failure_code or "PROVIDER_PENDING"
            transition_payout(intent, PayoutStatus.RECONCILIATION_REQUIRED)
            await self._event(
                intent,
                "payout.reconciliation_required",
                actor_id,
                {"code": intent.failure_code},
            )
        else:
            intent.failure_kind = PayoutFailureKind.UNKNOWN.value
            intent.failure_code = result.failure_code
            transition_payout(intent, PayoutStatus.RECONCILIATION_REQUIRED)
            await self._event(
                intent, "payout.reconciliation_required", actor_id, {"code": result.failure_code}
            )
            await self._notify_owner(
                intent,
                NotificationMessageKey.PAYOUT_RECONCILIATION_REQUIRED,
                "reconcile",
            )
        return await self.repo.save_intent(intent)

    async def reconcile(
        self,
        intent_id: uuid.UUID,
        owner: Account,
        outcome: PayoutSimulationOutcome | None = None,
    ) -> PayoutIntent:
        intent = await self._intent(intent_id, lock=True)
        self._verify_hash(intent)
        if PayoutStatus(intent.status) not in (
            PayoutStatus.RECONCILIATION_REQUIRED,
            PayoutStatus.EXECUTION_PENDING,
        ):
            raise PayoutTransitionError("payout does not require reconciliation")
        if outcome is not None:
            intent.simulation_outcome = outcome.value
        result = await self.provider.reconcile(intent)
        if result.status == PayoutProviderResult.SUCCEEDED:
            await self._finalize(intent, owner.id)
        elif result.status == PayoutProviderResult.FAILED:
            intent.failure_kind = PayoutFailureKind.PERMANENT.value
            transition_payout(intent, PayoutStatus.FAILED)
        elif result.status == PayoutProviderResult.PENDING:
            if PayoutStatus(intent.status) != PayoutStatus.RECONCILIATION_REQUIRED:
                transition_payout(intent, PayoutStatus.RECONCILIATION_REQUIRED)
        else:
            if PayoutStatus(intent.status) != PayoutStatus.RECONCILIATION_REQUIRED:
                transition_payout(intent, PayoutStatus.RECONCILIATION_REQUIRED)
        intent.reconciled_at = datetime.now(UTC)
        await self._event(
            intent,
            "payout.reconciled",
            owner.id,
            {"result": result.status.value, "simulated": True},
        )
        return await self.repo.save_intent(intent)

    async def begin_manual(self, intent_id: uuid.UUID, owner: Account) -> PayoutIntent:
        intent = await self._intent(intent_id, lock=True)
        self._verify_hash(intent)
        await self._execution_gate(intent, require_fresh=True, allow_manual=True)
        if PayoutStatus(intent.status) != PayoutStatus.APPROVED:
            raise PayoutTransitionError("only approved payout can await manual settlement")
        transition_payout(intent, PayoutStatus.AWAITING_MANUAL_SETTLEMENT)
        return await self.repo.save_intent(intent)

    async def complete_manual(
        self, intent_id: uuid.UUID, owner: Account, external_reference: str, evidence: str
    ) -> PayoutIntent:
        intent = await self._intent(intent_id, lock=True)
        self._verify_hash(intent)
        if PayoutStatus(intent.status) == PayoutStatus.SUCCEEDED:
            return intent
        if PayoutStatus(intent.status) != PayoutStatus.AWAITING_MANUAL_SETTLEMENT:
            raise PayoutTransitionError("payout is not awaiting manual settlement")
        if not external_reference.strip() or not evidence.strip():
            raise PayoutSafetyError("MANUAL_EVIDENCE_REQUIRED")
        await self._execution_gate(intent, require_fresh=True, allow_manual=True)
        intent.external_reference = external_reference.strip()
        await self._finalize(intent, owner.id)
        await self._event(
            intent, "payout.reconciled", owner.id, {"manual": True, "evidence_present": True}
        )
        return await self.repo.save_intent(intent)

    async def get(self, intent_id: uuid.UUID) -> PayoutIntent:
        return await self._intent(intent_id)

    async def get_or_create_for_withdrawal(self, withdrawal_id: uuid.UUID) -> PayoutIntent:
        existing = await self.repo.by_withdrawal(withdrawal_id)
        if existing:
            return existing
        withdrawal = await self.withdrawals.get_by_id_for_update(withdrawal_id)
        if withdrawal is None:
            raise PayoutNotFoundError()
        return await self.create_for_withdrawal(withdrawal)

    async def list(self, *, status: str | None, limit: int, offset: int):
        return await self.repo.list_intents(status=status, limit=limit, offset=offset)

    async def _execution_gate(
        self, intent: PayoutIntent, *, require_fresh: bool, allow_manual: bool = False
    ):
        approvals = await self.repo.approvals(intent.id)
        valid_approvers = {
            approval.approver_account_id
            for approval in approvals
            if approval.decision == PayoutApprovalDecision.APPROVED.value
            and approval.intent_hash == intent.intent_hash
        }
        if len(valid_approvers) < intent.required_approvals:
            raise PayoutSafetyError("REQUIRED_APPROVALS_MISSING")
        policy = await self.repo.active_policy(lock=True)
        if not settings.PAYOUT_ENABLED:
            raise PayoutSafetyError("PAYOUT_ENABLED_FALSE")
        if not policy.payouts_enabled:
            raise PayoutSafetyError("PAYOUT_BUSINESS_KILL_SWITCH")
        if not allow_manual:
            if intent.provider_mode == PayoutProviderMode.LIVE.value:
                await self._live_gate(intent, require_fresh=require_fresh)
            elif (
                settings.PAYOUT_PROVIDER_MODE != PayoutProviderMode.SIMULATED.value
                or not settings.PAYOUT_SIMULATION_ENABLED
            ):
                raise PayoutSafetyError("SIMULATED_PROVIDER_DISABLED")
            elif intent.provider_mode != PayoutProviderMode.SIMULATED.value:
                raise PayoutSafetyError("INTENT_PROVIDER_MODE_DISABLED")
        snapshot, decision, reason = await self._risk(execution=require_fresh)
        if decision == RiskDecision.BLOCK:
            raise PayoutSafetyError(reason.value if reason else "RISK_BLOCKED")
        await self._limits(intent, policy)
        return snapshot, decision, reason

    async def _live_gate(self, intent: PayoutIntent, *, require_fresh: bool) -> None:
        """Every gate a live Bybit withdrawal must pass before the state
        machine allows it past QUEUED (require_fresh=False, e.g. queue())
        or into EXECUTING (require_fresh=True, execute() only). Re-checked
        on every call - a readiness flag flipping between queue() and
        execute() is caught, not assumed to still hold."""
        if settings.PAYOUT_PROVIDER_MODE != PayoutProviderMode.LIVE.value:
            raise PayoutSafetyError("LIVE_PROVIDER_DISABLED")
        if intent.network != "TRC20":
            raise PayoutSafetyError("LIVE_NETWORK_NOT_SUPPORTED")
        readiness = await LivePayoutReadinessService(
            PayoutSecurityRepository(self.repo.session), self.repo, self.risk_repo
        ).evaluate()
        if not readiness.ready:
            raise PayoutSafetyError("LIVE_PAYOUT_NOT_READY")
        # readiness.checks["address_allowlist_configured"] only proves SOME
        # destination exists somewhere - it says nothing about whether THIS
        # intent's exact (beneficiary, address) pair is one of them. That
        # per-transaction check happens here, separately, every time.
        security = PayoutSecurityRepository(self.repo.session)
        fingerprint = destination_fingerprint(intent.asset, intent.network, intent.destination)
        destination = await security.destination_by_fingerprint(
            intent.beneficiary_account_id, fingerprint
        )
        if destination is None or not destination.enabled:
            raise PayoutSafetyError("DESTINATION_NOT_APPROVED_FOR_BENEFICIARY")
        if require_fresh:
            # Only the real network submission is cooled down - queue() does
            # no network I/O and must not consume the coin/chain slot.
            cooldown_key = f"bybit_live_withdraw:{intent.asset}:{intent.network}"
            limited = await self._rate_limiter.is_rate_limited(
                cooldown_key,
                max_requests=1,
                window_seconds=_BYBIT_WITHDRAW_COOLDOWN_SECONDS,
                fail_mode="closed",
            )
            if limited:
                raise PayoutSafetyError("BYBIT_WITHDRAW_COOLDOWN_ACTIVE")

    async def _risk(self, *, execution: bool):
        risk_policy = await self.risk_repo.active_policy(lock=execution)
        snapshot = await TreasurySnapshotService(self.risk_repo).current(risk_policy)
        if execution and snapshot.risk_status in (RiskStatus.STALE, RiskStatus.UNKNOWN):
            return snapshot, RiskDecision.BLOCK, RiskReason.RESERVE_DATA_STALE
        decision, reason = RiskDecisionService.reserve(snapshot, risk_policy)
        return snapshot, decision, reason

    async def _limits(self, intent: PayoutIntent, policy: PayoutPolicy) -> None:
        exposure = await self.repo.exposure(asset=intent.asset)
        checks = (
            (
                policy.max_single_payout_enabled,
                intent.amount,
                policy.max_single_payout_usdt,
                "MAX_SINGLE_PAYOUT",
            ),
            (
                policy.max_daily_payout_enabled,
                exposure["daily"] + intent.amount,
                policy.max_daily_payout_usdt,
                "MAX_DAILY_PAYOUT",
            ),
            (
                policy.max_hourly_payout_enabled,
                exposure["hourly"] + intent.amount,
                policy.max_hourly_payout_usdt,
                "MAX_HOURLY_PAYOUT",
            ),
            (
                policy.max_pending_payout_enabled,
                exposure["pending"],
                policy.max_pending_payout_usdt,
                "MAX_PENDING_PAYOUT",
            ),
            (
                policy.max_asset_exposure_enabled,
                exposure["pending"],
                policy.max_asset_exposure_usdt,
                "MAX_ASSET_EXPOSURE",
            ),
        )
        for enabled, current, threshold, code in checks:
            if enabled and threshold is not None and current > threshold:
                raise PayoutSafetyError(code)

    async def _finalize(self, intent: PayoutIntent, actor_id: uuid.UUID | None) -> None:
        withdrawal = await self._withdrawal(intent)
        if withdrawal.status == WithdrawalStatus.PAID:
            if PayoutStatus(intent.status) != PayoutStatus.SUCCEEDED:
                transition_payout(intent, PayoutStatus.SUCCEEDED)
            return
        if withdrawal.status != WithdrawalStatus.APPROVED:
            raise PayoutSafetyError("WITHDRAWAL_NOT_APPROVED")
        effective_actor = (
            actor_id or withdrawal.actioned_by_account_id or withdrawal.created_by_account_id
        )
        await self.wallet.pay_withdrawal(
            merchant_id=withdrawal.merchant_id,
            amount=withdrawal.amount,
            withdrawal_id=withdrawal.id,
            actor_id=effective_actor,
        )
        transition_withdrawal(withdrawal, WithdrawalStatus.PAID, effective_actor)
        transition_payout(intent, PayoutStatus.SUCCEEDED)
        await self.withdrawals.save(withdrawal)
        await self._notify_merchant(
            intent,
            NotificationMessageKey.WITHDRAWAL_COMPLETED,
            withdrawal.public_id,
            "completed",
        )

    async def _intent(self, intent_id: uuid.UUID, *, lock: bool = False) -> PayoutIntent:
        intent = await self.repo.get(intent_id, lock=lock)
        if intent is None:
            raise PayoutNotFoundError()
        return intent

    async def _withdrawal(self, intent: PayoutIntent) -> MerchantWithdrawal:
        withdrawal = await self.withdrawals.get_by_id_for_update(intent.withdrawal_id)
        if withdrawal is None:
            raise PayoutSafetyError("WITHDRAWAL_NOT_FOUND")
        return withdrawal

    @staticmethod
    def _verify_hash(intent: PayoutIntent) -> None:
        if intent.intent_hash != intent_hash(intent):
            raise PayoutSafetyError("PAYOUT_INTENT_CHANGED")

    async def _event(
        self,
        intent: PayoutIntent,
        event: str,
        actor_id: uuid.UUID | None = None,
        metadata: dict | None = None,
    ) -> None:
        safe = metadata or {}
        await self.repo.event(intent.id, event, actor_id, safe)
        if self.audit:
            await self.audit.log_action(
                action=event,
                entity_type="payout",
                entity_id=str(intent.id),
                actor_account_id=actor_id,
                actor_role="owner" if actor_id else "system",
                audit_metadata=safe,
            )
        if self.realtime:
            await self.realtime.enqueue_payout(intent, withdrawal_id=intent.withdrawal_id)

    async def _notify_owner(
        self, intent: PayoutIntent, message_key: NotificationMessageKey, suffix: str
    ) -> None:
        if not self.notifications:
            return
        owner = await self.accounts.get_by_role(UserRole.OWNER)
        if owner:
            await self.notifications.emit_semantic_notification(
                owner.id,
                NotificationType.PAYOUT_ACTION_REQUIRED,
                message_key,
                {"reference": str(intent.id)[:8]},
                payload={"payout_intent_id": str(intent.id)},
                dedupe_key=f"payout:{intent.id}:{suffix}",
            )

    async def _notify_merchant(
        self,
        intent: PayoutIntent,
        message_key: NotificationMessageKey,
        withdrawal_reference: str,
        suffix: str,
    ) -> None:
        if self.notifications:
            await self.notifications.emit_semantic_notification(
                intent.beneficiary_account_id,
                NotificationType.WITHDRAWAL_STATUS_CHANGED,
                message_key,
                {"reference": withdrawal_reference},
                payload={
                    "withdrawal_id": str(intent.withdrawal_id),
                    "payout_status": intent.status,
                },
                dedupe_key=f"payout:{intent.id}:{suffix}",
            )
