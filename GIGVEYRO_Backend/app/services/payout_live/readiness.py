from dataclasses import dataclass

from app.core.config import settings
from app.enums.payout import LivePayoutBlocker, LivePayoutCapability
from app.infra.metrics import observe_live_payout_readiness
from app.repositories.payout import PayoutRepository
from app.repositories.payout_security import PayoutSecurityRepository
from app.repositories.risk import RiskRepository


@dataclass(frozen=True, slots=True)
class LivePayoutReadiness:
    ready: bool
    capabilities: list[str]
    blocking_reasons: list[str]
    checks: dict[str, bool]


class LivePayoutReadinessService:
    def __init__(
        self,
        security: PayoutSecurityRepository,
        payouts: PayoutRepository,
        risk: RiskRepository,
    ) -> None:
        self.security = security
        self.payouts = payouts
        self.risk = risk

    async def evaluate(self) -> LivePayoutReadiness:
        payout_policy = await self.payouts.active_policy()
        risk_policy = await self.risk.active_policy()
        credentials = bool(
            settings.BYBIT_WRITE_API_KEY.get_secret_value()
            and settings.BYBIT_WRITE_API_SECRET.get_secret_value()
        )
        destinations = await self.security.enabled_destination_count()
        networks = await self.security.enabled_network_count()
        risk_ready = bool(
            risk_policy.reserve_coverage_enabled
            and risk_policy.minimum_external_reserve_enabled
            and risk_policy.minimum_external_usdt_reserve is not None
        )
        dual_ready = (
            payout_policy.default_required_approvals >= 2
            and payout_policy.high_value_required_approvals >= 2
        )
        checks = {
            "global_payout_enabled": settings.PAYOUT_ENABLED,
            "provider_live": settings.PAYOUT_PROVIDER_MODE == "live",
            "write_enabled": settings.BYBIT_WRITE_ENABLED,
            "write_credentials_configured": credentials,
            "write_permission_verified": settings.BYBIT_WRITE_PERMISSION_VERIFIED,
            "ip_whitelist_verified": settings.BYBIT_WRITE_IP_WHITELIST_VERIFIED,
            "address_allowlist_configured": destinations > 0,
            "network_allowlist_configured": networks > 0,
            "business_payouts_enabled": payout_policy.payouts_enabled,
            "risk_policy_ready": risk_ready,
            "dual_approval_ready": dual_ready,
            "reconciliation_ready": settings.BYBIT_LIVE_RECONCILIATION_VERIFIED,
            # The write transport (BybitWritePayoutClient / BybitLivePayoutProvider)
            # exists in code unconditionally - this check is not "has the network
            # code been written" (it always has), it is "is the write path not
            # itself disabled", i.e. mirrors write_enabled. It stays a distinct
            # check (rather than folded into write_enabled) so a future provider
            # swap or a code-level kill switch has an independent place to hook.
            "write_network_transport_available": settings.BYBIT_WRITE_ENABLED,
        }
        mapping = {
            "global_payout_enabled": LivePayoutBlocker.PAYOUT_GLOBAL_DISABLED,
            "provider_live": LivePayoutBlocker.PROVIDER_NOT_LIVE,
            "write_credentials_configured": LivePayoutBlocker.WRITE_CREDENTIALS_MISSING,
            "write_permission_verified": LivePayoutBlocker.WRITE_PERMISSION_UNVERIFIED,
            "ip_whitelist_verified": LivePayoutBlocker.IP_WHITELIST_REQUIRED,
            "address_allowlist_configured": LivePayoutBlocker.NO_APPROVED_DESTINATION,
            "network_allowlist_configured": LivePayoutBlocker.NO_ALLOWED_NETWORK,
            "business_payouts_enabled": LivePayoutBlocker.BUSINESS_PAYOUTS_DISABLED,
            "risk_policy_ready": LivePayoutBlocker.RISK_POLICY_NOT_READY,
            "dual_approval_ready": LivePayoutBlocker.DUAL_APPROVAL_NOT_READY,
            "reconciliation_ready": LivePayoutBlocker.RECONCILIATION_NOT_READY,
            "write_network_transport_available": LivePayoutBlocker.WRITE_NETWORK_TRANSPORT_DISABLED,
        }
        blockers = [reason.value for check, reason in mapping.items() if not checks[check]]
        capabilities: list[str] = []
        if settings.BYBIT_PRIVATE_ENABLED:
            capabilities.append(LivePayoutCapability.READ_ONLY.value)
        if not credentials:
            capabilities.append(LivePayoutCapability.WRITE_CREDENTIALS_MISSING.value)
        if not settings.BYBIT_WRITE_PERMISSION_VERIFIED:
            capabilities.append(LivePayoutCapability.WRITE_PERMISSION_MISSING.value)
        if networks:
            capabilities.append(LivePayoutCapability.DRY_RUN_READY.value)
        if not settings.BYBIT_PRIVATE_ENABLED and not credentials:
            capabilities.insert(0, LivePayoutCapability.NOT_CONFIGURED.value)
        ready = not blockers
        capabilities.append(
            LivePayoutCapability.LIVE_READY.value
            if ready
            else LivePayoutCapability.LIVE_DISABLED.value
        )
        observe_live_payout_readiness(ready, [item.value for item in LivePayoutBlocker], blockers)
        return LivePayoutReadiness(ready, capabilities, blockers, checks)
