import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.enums.account import UserRole
from app.enums.fees import FeePayer, FeePolicyStatus, FeeType
from app.models.account import Account
from app.models.fees import FeePolicy, FeePolicyComponent
from app.repositories.fees import FeeRepository

MONEY_QUANTUM = Decimal("0.00000001")
BPS_DENOMINATOR = Decimal("10000")
ENFORCED_FEE_TYPES = {FeeType.FIAT_CONVERSION}


class FeePolicyNotFoundError(Exception):
    pass


class FeePolicyValidationError(Exception):
    pass


class FeePolicyPermissionError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class FeeTerms:
    enabled: bool
    percent_bps: int
    fixed_fee: Decimal
    min_fee: Decimal | None = None
    max_fee: Decimal | None = None
    payer: str | None = None


@dataclass(frozen=True, slots=True)
class FeeCalculation:
    gross: Decimal
    percent_fee: Decimal
    fixed_fee: Decimal
    total_fee: Decimal
    net: Decimal


class FeeCalculator:
    """Pure deterministic fee arithmetic; never reads or mutates the database."""

    @staticmethod
    def validate_terms(terms: FeeTerms) -> None:
        if not 0 <= terms.percent_bps <= 5000:
            raise FeePolicyValidationError("percent_bps must be between 0 and 5000")
        values = (terms.fixed_fee, terms.min_fee, terms.max_fee)
        if any(value is not None and (not value.is_finite() or value < 0) for value in values):
            raise FeePolicyValidationError("Fee values must be non-negative finite Decimals")
        if (
            terms.min_fee is not None
            and terms.max_fee is not None
            and terms.min_fee > terms.max_fee
        ):
            raise FeePolicyValidationError("min_fee cannot exceed max_fee")

    @staticmethod
    def calculate(amount: Decimal, terms: FeeTerms) -> FeeCalculation:
        FeeCalculator.validate_terms(terms)
        if not amount.is_finite() or amount < 0:
            raise FeePolicyValidationError("Amount must be a non-negative finite Decimal")
        gross = amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        if not terms.enabled:
            return FeeCalculation(gross, Decimal("0E-8"), Decimal("0E-8"), Decimal("0E-8"), gross)
        percent = (gross * Decimal(terms.percent_bps) / BPS_DENOMINATOR).quantize(
            MONEY_QUANTUM, rounding=ROUND_HALF_UP
        )
        fixed = terms.fixed_fee.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        total = percent + fixed
        if terms.min_fee is not None:
            total = max(total, terms.min_fee.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP))
        if terms.max_fee is not None:
            total = min(total, terms.max_fee.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP))
        total = total.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        if total > gross:
            raise FeePolicyValidationError("Fee cannot exceed gross amount")
        return FeeCalculation(gross, percent, fixed, total, gross - total)


def component_terms(component: FeePolicyComponent) -> FeeTerms:
    return FeeTerms(
        enabled=component.enabled,
        percent_bps=component.percent_bps,
        fixed_fee=component.fixed_fee,
        min_fee=component.min_fee,
        max_fee=component.max_fee,
        payer=component.payer,
    )


def policy_component(policy: FeePolicy, fee_type: FeeType) -> FeePolicyComponent:
    for component in policy.components:
        if component.fee_type == fee_type.value:
            return component
    raise FeePolicyValidationError(f"Policy is missing {fee_type.value}")


class FeePolicyService:
    def __init__(self, repository: FeeRepository) -> None:
        self._fees = repository

    async def active(self, *, lock: bool = False) -> FeePolicy:
        return await self._fees.active_policy(lock=lock)

    async def policy(self, policy_id: uuid.UUID) -> FeePolicy:
        policy = await self._fees.policy_by_id(policy_id)
        if policy is None:
            raise FeePolicyNotFoundError()
        return policy

    async def create(self, actor: Account, components: dict[FeeType, FeeTerms]) -> FeePolicy:
        self._require_owner(actor)
        if set(components) != set(FeeType):
            raise FeePolicyValidationError("Every fee component must be supplied")
        policies = await self._fees.lock_all_policies()
        version = max((item.version for item in policies), default=0) + 1
        policy = FeePolicy(
            version=version,
            status=FeePolicyStatus.DRAFT.value,
            created_by_account_id=actor.id,
            components=[
                FeePolicyComponent(
                    fee_type=fee_type.value,
                    enabled=terms.enabled,
                    percent_bps=terms.percent_bps,
                    fixed_fee=terms.fixed_fee,
                    min_fee=terms.min_fee,
                    max_fee=terms.max_fee,
                    payer=terms.payer,
                )
                for fee_type, terms in components.items()
            ],
        )
        for component in policy.components:
            FeeCalculator.validate_terms(component_terms(component))
        return await self._fees.create_policy(policy)

    async def activate(self, actor: Account, policy_id: uuid.UUID) -> FeePolicy:
        self._require_owner(actor)
        policies = await self._fees.lock_all_policies()
        target = next((item for item in policies if item.id == policy_id), None)
        if target is None:
            raise FeePolicyNotFoundError()
        if target.status == FeePolicyStatus.ACTIVE.value:
            return target
        if target.status != FeePolicyStatus.DRAFT.value:
            raise FeePolicyValidationError("Only a draft policy can be activated")
        unsupported = [
            component.fee_type
            for component in target.components
            if component.enabled and FeeType(component.fee_type) not in ENFORCED_FEE_TYPES
        ]
        if unsupported:
            raise FeePolicyValidationError(
                "Cannot activate unenforced fee components: " + ", ".join(sorted(unsupported))
            )
        conversion = policy_component(target, FeeType.FIAT_CONVERSION)
        if conversion.enabled and conversion.payer != FeePayer.USER.value:
            raise FeePolicyValidationError("Fiat conversion spread payer must be USER")
        now = datetime.now(UTC)
        for policy in policies:
            if policy.status == FeePolicyStatus.ACTIVE.value:
                policy.status = FeePolicyStatus.RETIRED.value
        # Retire first so PostgreSQL's partial unique active-policy index is
        # never transiently violated by ORM update ordering.
        await self._fees.flush()
        target.status = FeePolicyStatus.ACTIVE.value
        target.effective_from = now
        target.activated_at = now
        return await self._fees.save_policy(target)

    async def summary(self) -> dict[str, list[dict]]:
        now = datetime.now(UTC)
        starts = {
            "today": now.replace(hour=0, minute=0, second=0, microsecond=0),
            "7d": now - timedelta(days=7),
            "30d": now - timedelta(days=30),
            "all": None,
        }
        output = {}
        for period, since in starts.items():
            rows = await self._fees.profit_summary(since)
            output[period] = [
                {
                    "currency": currency,
                    "fee_type": fee_type,
                    "gross_volume": gross,
                    "total_fees": fees,
                    "transaction_count": count,
                    "average_fee": average,
                }
                for currency, fee_type, gross, fees, count, average in rows
            ]
        return output

    @staticmethod
    def _require_owner(actor: Account) -> None:
        if actor.role != UserRole.OWNER:
            raise FeePolicyPermissionError("OWNER required")
