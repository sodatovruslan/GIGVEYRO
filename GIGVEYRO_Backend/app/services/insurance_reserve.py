import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.models.account import Account
from app.models.insurance_reserve import InsuranceReservePolicy
from app.repositories.insurance_reserve import InsuranceReservePolicyRepository

BPS_DIVISOR = Decimal("100")


class InsuranceReservePolicyError(Exception):
    pass


class InsuranceReservePolicyNotFoundError(InsuranceReservePolicyError):
    pass


def compute_required_minimum_reserve(basis: Decimal, percentage: Decimal) -> Decimal:
    """The one formula for the insurance reserve floor - used identically by
    the enforcement gate (WalletService._apply_bucket_change) and by the
    Owner-facing report, so the two can never silently disagree."""
    return (basis * percentage / BPS_DIVISOR).quantize(Decimal("0.00000001"))


class InsuranceReservePolicyService:
    """Draft -> active -> retired versioned policy, same shape as
    RiskPolicyService / PayoutPolicyService."""

    def __init__(self, repo: InsuranceReservePolicyRepository) -> None:
        self.repo = repo

    async def create(self, actor: Account, values: dict) -> InsuranceReservePolicy:
        policies = await self.repo.lock_policies()
        return await self.repo.save_policy(
            InsuranceReservePolicy(
                version=max((p.version for p in policies), default=0) + 1,
                status="draft",
                created_by_account_id=actor.id,
                **values,
            )
        )

    async def activate(self, policy_id: uuid.UUID) -> InsuranceReservePolicy:
        policies = await self.repo.lock_policies()
        target = next((p for p in policies if p.id == policy_id), None)
        if target is None:
            raise InsuranceReservePolicyNotFoundError()
        if target.status == "active":
            return target
        if target.status != "draft":
            raise InsuranceReservePolicyError("only a draft policy can be activated")
        now = datetime.now(UTC)
        for policy in policies:
            if policy.status == "active":
                policy.status = "retired"
        # Flush the retirement(s) before activating the new version: the
        # partial unique index on status='active' is checked immediately
        # (not deferred), so both updates must never be visible to Postgres
        # as "active" at the same instant.
        await self.repo.session.flush()
        target.status = "active"
        target.activated_at = now
        return await self.repo.save_policy(target)
