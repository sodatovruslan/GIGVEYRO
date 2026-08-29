from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.enums.payout import PayoutProviderResult, PayoutSimulationOutcome
from app.models.payout import PayoutIntent


@dataclass(frozen=True, slots=True)
class ProviderPayoutResult:
    status: PayoutProviderResult
    external_reference: str | None = None
    failure_code: str | None = None


class ExchangePayoutProvider(ABC):
    """Write-provider boundary. It intentionally has no relationship to Bybit read-only code."""

    @abstractmethod
    async def prepare(self, intent: PayoutIntent) -> None: ...

    @abstractmethod
    async def execute(self, intent: PayoutIntent) -> ProviderPayoutResult: ...

    @abstractmethod
    async def get_status(self, intent: PayoutIntent) -> ProviderPayoutResult: ...

    async def reconcile(self, intent: PayoutIntent) -> ProviderPayoutResult:
        return await self.get_status(intent)


class DisabledPayoutProvider(ExchangePayoutProvider):
    async def prepare(self, intent: PayoutIntent) -> None:
        raise RuntimeError("payout provider is disabled")

    async def execute(self, intent: PayoutIntent) -> ProviderPayoutResult:
        raise RuntimeError("payout provider is disabled")

    async def get_status(self, intent: PayoutIntent) -> ProviderPayoutResult:
        return ProviderPayoutResult(PayoutProviderResult.UNKNOWN)


class SimulatedPayoutProvider(ExchangePayoutProvider):
    """Deterministic local simulator. Never performs network I/O."""

    async def prepare(self, intent: PayoutIntent) -> None:
        return None

    async def execute(self, intent: PayoutIntent) -> ProviderPayoutResult:
        reference = f"SIM-{intent.id}"
        outcome = PayoutSimulationOutcome(intent.simulation_outcome or "succeeded")
        if outcome == PayoutSimulationOutcome.SUCCEEDED:
            return ProviderPayoutResult(PayoutProviderResult.SUCCEEDED, reference)
        if outcome == PayoutSimulationOutcome.FAILED:
            return ProviderPayoutResult(PayoutProviderResult.FAILED, reference, "SIMULATED_FAILURE")
        if outcome == PayoutSimulationOutcome.PENDING:
            return ProviderPayoutResult(PayoutProviderResult.PENDING, reference)
        return ProviderPayoutResult(PayoutProviderResult.UNKNOWN, reference, "SIMULATED_UNKNOWN")

    async def get_status(self, intent: PayoutIntent) -> ProviderPayoutResult:
        return await self.execute(intent)
