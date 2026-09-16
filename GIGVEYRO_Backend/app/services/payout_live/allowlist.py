import uuid
from datetime import UTC, datetime

from app.models.account import Account
from app.models.payout import PayoutDestination, PayoutNetwork
from app.repositories.payout_security import PayoutSecurityRepository
from app.services.audit import AuditService
from app.services.payout_live.bybit import (
    LivePayoutSecurityError,
    destination_fingerprint,
    mask_live_destination,
    validate_tron_base58check,
)


class PayoutAllowlistService:
    def __init__(self, repo: PayoutSecurityRepository, audit: AuditService | None = None) -> None:
        self.repo = repo
        self.audit = audit

    async def create_destination(
        self,
        *,
        owner: Account,
        beneficiary_account_id: uuid.UUID,
        label: str,
        asset: str,
        network: str,
        address: str,
    ) -> PayoutDestination:
        asset = asset.upper()
        network = network.upper()
        if asset != "USDT":
            raise LivePayoutSecurityError("ASSET_NOT_ALLOWED")
        if network != "TRC20" or await self.repo.enabled_network(asset, network) is None:
            raise LivePayoutSecurityError("NETWORK_NOT_ALLOWED")
        validate_tron_base58check(address)
        fingerprint = destination_fingerprint(asset, network, address)
        existing = await self.repo.destination_by_fingerprint(beneficiary_account_id, fingerprint)
        if existing:
            return existing
        destination = await self.repo.save_destination(
            PayoutDestination(
                label=label.strip(),
                asset=asset,
                network=network,
                address=address,
                masked_address=mask_live_destination(address),
                fingerprint=fingerprint,
                enabled=True,
                beneficiary_account_id=beneficiary_account_id,
                created_by_account_id=owner.id,
            )
        )
        if self.audit:
            await self.audit.log_action(
                action="payout_address.created",
                entity_type="payout_address",
                entity_id=str(destination.id),
                actor_account_id=owner.id,
                actor_role=owner.role.value,
                audit_metadata={
                    "asset": asset,
                    "network": network,
                    "fingerprint": fingerprint,
                    "beneficiary_account_id": str(beneficiary_account_id),
                },
            )
        return destination

    async def ensure_destination_for_beneficiary(
        self,
        *,
        beneficiary_account_id: uuid.UUID,
        actor_role: str,
        label: str,
        asset: str,
        network: str,
        address: str,
    ) -> PayoutDestination:
        """System-triggered, idempotent variant of create_destination for the
        beneficiary's own withdrawal flow - no separate Owner pre-approval
        step exists in this model, the beneficiary supplies their own
        address when creating the withdrawal. Re-validates structurally
        regardless of any earlier validation, since this is a security-
        relevant record, not just a display convenience."""
        asset = asset.upper()
        network = network.upper()
        if asset != "USDT" or network != "TRC20":
            raise LivePayoutSecurityError("NETWORK_NOT_ALLOWED")
        validate_tron_base58check(address)
        fingerprint = destination_fingerprint(asset, network, address)
        existing = await self.repo.destination_by_fingerprint(beneficiary_account_id, fingerprint)
        if existing:
            return existing
        destination = await self.repo.save_destination(
            PayoutDestination(
                label=label.strip()[:100] or "Withdrawal destination",
                asset=asset,
                network=network,
                address=address,
                masked_address=mask_live_destination(address),
                fingerprint=fingerprint,
                enabled=True,
                beneficiary_account_id=beneficiary_account_id,
                created_by_account_id=beneficiary_account_id,
            )
        )
        if self.audit:
            await self.audit.log_action(
                action="payout_address.auto_registered",
                entity_type="payout_address",
                entity_id=str(destination.id),
                actor_account_id=beneficiary_account_id,
                actor_role=actor_role,
                audit_metadata={
                    "asset": asset,
                    "network": network,
                    "fingerprint": fingerprint,
                },
            )
        return destination

    async def disable_destination(
        self, destination_id: uuid.UUID, owner: Account
    ) -> PayoutDestination:
        destination = await self.repo.destination(destination_id, lock=True)
        if destination is None:
            raise LivePayoutSecurityError("DESTINATION_NOT_FOUND")
        if not destination.enabled:
            return destination
        destination.enabled = False
        destination.disabled_at = datetime.now(UTC)
        destination.disabled_by_account_id = owner.id
        await self.repo.save_destination(destination)
        if self.audit:
            await self.audit.log_action(
                action="payout_address.disabled",
                entity_type="payout_address",
                entity_id=str(destination.id),
                actor_account_id=owner.id,
                actor_role=owner.role.value,
                audit_metadata={
                    "asset": destination.asset,
                    "network": destination.network,
                    "fingerprint": destination.fingerprint,
                },
            )
        return destination

    async def disable_network(self, network_id: uuid.UUID, owner: Account) -> PayoutNetwork:
        network = await self.repo.network(network_id, lock=True)
        if network is None:
            raise LivePayoutSecurityError("NETWORK_NOT_FOUND")
        if not network.enabled:
            return network
        network.enabled = False
        network.disabled_at = datetime.now(UTC)
        network.disabled_by_account_id = owner.id
        await self.repo.save_network(network)
        if self.audit:
            await self.audit.log_action(
                action="payout_network.disabled",
                entity_type="payout_network",
                entity_id=str(network.id),
                actor_account_id=owner.id,
                actor_role=owner.role.value,
                audit_metadata={"asset": network.asset, "network": network.network},
            )
        return network
