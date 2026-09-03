from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import settings
from app.enums.account import UserRole
from app.enums.deposit import (
    CorrelationStatus,
    DepositAsset,
    DepositNetwork,
    DepositStatus,
    ReconciliationActionType,
    ReconciliationStatus,
)
from app.models.account import Account
from app.models.deposit import Deposit, DepositReconciliationAction, UnmatchedTransfer
from app.repositories.deposit import DepositRepository
from app.services.audit import AuditService
from app.services.deposit import DepositService
from app.services.realtime import RealtimeEventService


class DepositReconciliationError(Exception):
    def __init__(self, code: str, *, http_status: int = 409):
        super().__init__(code)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class ReconciliationResult:
    transfer: UnmatchedTransfer
    result_code: str
    deposit: Deposit | None = None
    replayed: bool = False


class DepositReconciliationService:
    def __init__(
        self,
        repository: DepositRepository,
        deposit_service: DepositService,
        audit: AuditService,
        realtime: RealtimeEventService | None = None,
    ) -> None:
        self.repo = repository
        self.deposits = deposit_service
        self.audit = audit
        self.realtime = realtime

    async def detail(
        self, transfer_id: uuid.UUID
    ) -> tuple[UnmatchedTransfer, list[Deposit], list[DepositReconciliationAction]]:
        transfer = await self.repo.get_unmatched_by_id(transfer_id)
        if transfer is None:
            raise DepositReconciliationError("TRANSFER_NOT_FOUND", http_status=404)
        candidates = await self.repo.list_reconciliation_candidates(transfer)
        history = await self.repo.list_reconciliation_actions(transfer.id)
        return transfer, candidates, history

    async def link(
        self,
        transfer_id: uuid.UUID,
        deposit_id: uuid.UUID,
        actor: Account,
        idempotency_key: str,
    ) -> ReconciliationResult:
        self._ensure_owner(actor)
        request_hash = self._request_hash(
            ReconciliationActionType.LINK, transfer_id, str(deposit_id)
        )
        replay = await self._idempotent_result(actor.id, idempotency_key, request_hash)
        if replay:
            return replay
        transfer = await self._transfer_for_action(transfer_id)
        result = await self._link_locked(transfer, deposit_id, actor)
        await self._record_action(
            transfer,
            actor,
            ReconciliationActionType.LINK,
            idempotency_key,
            request_hash,
            result.result_code,
            deposit_id,
        )
        return result

    async def reprocess(
        self, transfer_id: uuid.UUID, actor: Account, idempotency_key: str
    ) -> ReconciliationResult:
        self._ensure_owner(actor)
        request_hash = self._request_hash(ReconciliationActionType.REPROCESS, transfer_id, None)
        replay = await self._idempotent_result(actor.id, idempotency_key, request_hash)
        if replay:
            return replay
        transfer = await self._transfer_for_action(transfer_id)
        self._ensure_actionable(transfer)
        candidates = await self.repo.list_reconciliation_candidates(transfer)
        exact = [
            candidate for candidate in candidates if candidate.expected_amount == transfer.amount
        ]
        if len(exact) == 1:
            result = await self._link_locked(transfer, exact[0].id, actor)
        else:
            transfer.correlation_status = (
                CorrelationStatus.AMBIGUOUS if len(exact) > 1 else CorrelationStatus.UNMATCHED
            )
            transfer.reconciliation_status = ReconciliationStatus.REPROCESSED
            transfer.last_result_code = "AMBIGUOUS_MATCH" if exact else "NO_MATCH"
            transfer = await self.repo.save_unmatched(transfer)
            result = ReconciliationResult(transfer, transfer.last_result_code)
        await self._audit(
            "deposit_reconciliation.reprocessed",
            transfer,
            actor,
            result.result_code,
        )
        await self._record_action(
            transfer,
            actor,
            ReconciliationActionType.REPROCESS,
            idempotency_key,
            request_hash,
            result.result_code,
            result.deposit.id if result.deposit else None,
        )
        return result

    async def ignore(
        self,
        transfer_id: uuid.UUID,
        actor: Account,
        reason: str,
        idempotency_key: str,
    ) -> ReconciliationResult:
        self._ensure_owner(actor)
        request_hash = self._request_hash(ReconciliationActionType.IGNORE, transfer_id, reason)
        replay = await self._idempotent_result(actor.id, idempotency_key, request_hash)
        if replay:
            return replay
        transfer = await self._transfer_for_action(transfer_id)
        self._ensure_actionable(transfer)
        transfer.reconciliation_status = ReconciliationStatus.IGNORED
        transfer.resolution_reason = reason
        transfer.resolved_by_account_id = actor.id
        transfer.resolved_at = datetime.now(UTC)
        transfer.last_result_code = "IGNORED"
        transfer = await self.repo.save_unmatched(transfer)
        await self._audit("deposit_reconciliation.ignored", transfer, actor, "IGNORED")
        await self._record_action(
            transfer,
            actor,
            ReconciliationActionType.IGNORE,
            idempotency_key,
            request_hash,
            "IGNORED",
            None,
        )
        return ReconciliationResult(transfer, "IGNORED")

    async def record_link_failure(
        self,
        transfer_id: uuid.UUID,
        deposit_id: uuid.UUID,
        actor: Account,
        idempotency_key: str,
        error: DepositReconciliationError,
    ) -> None:
        """Persist one safe failure result when the API returns a handled error response."""
        if error.code in {"TRANSFER_NOT_FOUND", "IDEMPOTENCY_CONFLICT"}:
            return
        transfer = await self.repo.get_unmatched_by_id(transfer_id)
        if transfer is None:
            return
        existing = await self.repo.get_reconciliation_action(actor.id, idempotency_key)
        if existing is not None:
            return
        request_hash = self._request_hash(
            ReconciliationActionType.LINK, transfer_id, str(deposit_id)
        )
        result_code = f"ERROR:{error.code}"
        transfer.last_result_code = result_code
        await self.repo.save_unmatched(transfer)
        await self._audit("deposit_reconciliation.credit_failed", transfer, actor, result_code)
        await self._record_action(
            transfer,
            actor,
            ReconciliationActionType.LINK,
            idempotency_key,
            request_hash,
            result_code,
            deposit_id if error.code != "DEPOSIT_NOT_FOUND" else None,
        )

    async def _link_locked(
        self, transfer: UnmatchedTransfer, deposit_id: uuid.UUID, actor: Account
    ) -> ReconciliationResult:
        self._ensure_actionable(transfer)
        deposit = await self.repo.get_by_id_for_update(deposit_id)
        if deposit is None:
            raise DepositReconciliationError("DEPOSIT_NOT_FOUND", http_status=404)
        self._validate_link(transfer, deposit)
        used = await self.repo.get_by_provider_event_id(transfer.provider_event_id)
        if used is not None and used.id != deposit.id:
            raise DepositReconciliationError("TRANSFER_ALREADY_LINKED")

        credited = await self.deposits.ingest_transaction_event(
            deposit.id,
            tx_hash=transfer.tx_hash,
            amount=transfer.amount,
            confirmations=transfer.confirmations,
            network=transfer.network,
            asset=DepositAsset.USDT,
            destination_address=transfer.to_address,
            provider_event_id=transfer.provider_event_id,
        )
        if credited.status != DepositStatus.CREDITED:
            raise DepositReconciliationError("STALE_STATE")

        transfer.correlation_status = CorrelationStatus.MATCHED
        transfer.reconciliation_status = ReconciliationStatus.CREDITED
        transfer.linked_deposit_id = deposit.id
        transfer.resolved_by_account_id = actor.id
        transfer.resolved_at = datetime.now(UTC)
        transfer.last_result_code = "CREDITED"
        transfer = await self.repo.save_unmatched(transfer)
        await self._audit("deposit_reconciliation.linked", transfer, actor, "CREDITED")
        await self._audit("deposit_reconciliation.credit_succeeded", transfer, actor, "CREDITED")
        if self.realtime:
            await self.realtime.enqueue_deposit_updated(credited)
        return ReconciliationResult(transfer, "CREDITED", credited)

    def _validate_link(self, transfer: UnmatchedTransfer, deposit: Deposit) -> None:
        if transfer.network != DepositNetwork.TRC20 or deposit.network != DepositNetwork.TRC20:
            raise DepositReconciliationError("NETWORK_MISMATCH")
        if transfer.asset_contract != settings.USDT_TRC20_CONTRACT_ADDRESS:
            raise DepositReconciliationError("TOKEN_MISMATCH")
        if deposit.asset != DepositAsset.USDT:
            raise DepositReconciliationError("TOKEN_MISMATCH")
        if transfer.to_address != deposit.deposit_address:
            raise DepositReconciliationError("ADDRESS_MISMATCH")
        if not transfer.is_finalized or transfer.confirmations < deposit.required_confirmations:
            raise DepositReconciliationError("TRANSFER_NOT_FINAL")
        if deposit.status == DepositStatus.CREDITED:
            raise DepositReconciliationError("DEPOSIT_ALREADY_CREDITED")
        if deposit.status == DepositStatus.EXPIRED or deposit.expires_at <= datetime.now(UTC):
            raise DepositReconciliationError("DEPOSIT_EXPIRED")
        if deposit.status != DepositStatus.WAITING:
            raise DepositReconciliationError("STALE_STATE")
        if transfer.amount != deposit.expected_amount:
            raise DepositReconciliationError("AMOUNT_MISMATCH", http_status=422)

    @staticmethod
    def _ensure_actionable(transfer: UnmatchedTransfer) -> None:
        if transfer.reconciliation_status == ReconciliationStatus.CREDITED:
            raise DepositReconciliationError("TRANSFER_ALREADY_CREDITED")
        if transfer.reconciliation_status == ReconciliationStatus.IGNORED:
            raise DepositReconciliationError("TRANSFER_IGNORED")
        if transfer.linked_deposit_id is not None:
            raise DepositReconciliationError("TRANSFER_ALREADY_LINKED")

    @staticmethod
    def _ensure_owner(actor: Account) -> None:
        if actor.role != UserRole.OWNER:
            raise DepositReconciliationError("OWNER_REQUIRED", http_status=403)

    async def _transfer_for_action(self, transfer_id: uuid.UUID) -> UnmatchedTransfer:
        transfer = await self.repo.get_unmatched_by_id_for_update(transfer_id)
        if transfer is None:
            raise DepositReconciliationError("TRANSFER_NOT_FOUND", http_status=404)
        return transfer

    async def _idempotent_result(
        self, actor_id: uuid.UUID, idempotency_key: str, request_hash: str
    ) -> ReconciliationResult | None:
        await self.repo.lock_reconciliation_idempotency(actor_id, idempotency_key)
        existing = await self.repo.get_reconciliation_action(actor_id, idempotency_key)
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise DepositReconciliationError("IDEMPOTENCY_CONFLICT")
        if existing.result_code.startswith("ERROR:"):
            code = existing.result_code.removeprefix("ERROR:")
            raise DepositReconciliationError(
                code,
                http_status=self._error_status(code),
            )
        transfer = await self.repo.get_unmatched_by_id(existing.transfer_id)
        if transfer is None:
            raise DepositReconciliationError("TRANSFER_NOT_FOUND", http_status=404)
        deposit = await self.repo.get_by_id(existing.deposit_id) if existing.deposit_id else None
        return ReconciliationResult(transfer, existing.result_code, deposit, replayed=True)

    async def _record_action(
        self,
        transfer: UnmatchedTransfer,
        actor: Account,
        action: ReconciliationActionType,
        idempotency_key: str,
        request_hash: str,
        result_code: str,
        deposit_id: uuid.UUID | None,
    ) -> None:
        await self.repo.create_reconciliation_action(
            DepositReconciliationAction(
                transfer_id=transfer.id,
                actor_account_id=actor.id,
                action=action,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                deposit_id=deposit_id,
                result_code=result_code,
            )
        )

    async def _audit(
        self,
        action: str,
        transfer: UnmatchedTransfer,
        actor: Account,
        result_code: str,
    ) -> None:
        await self.audit.log_action(
            action=action,
            entity_type="unmatched_transfer",
            entity_id=str(transfer.id),
            actor_account_id=actor.id,
            actor_role=UserRole.OWNER.value,
            audit_metadata={
                "transfer_id": str(transfer.id),
                "deposit_id": (
                    str(transfer.linked_deposit_id) if transfer.linked_deposit_id else None
                ),
                "result": result_code,
                "reconciliation_status": transfer.reconciliation_status.value,
                "reason": transfer.resolution_reason,
            },
        )

    @staticmethod
    def _request_hash(
        action: ReconciliationActionType,
        transfer_id: uuid.UUID,
        value: str | None,
    ) -> str:
        payload = json.dumps(
            {"action": action.value, "transfer_id": str(transfer_id), "value": value},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _error_status(code: str) -> int:
        if code == "DEPOSIT_NOT_FOUND":
            return 404
        if code == "AMOUNT_MISMATCH":
            return 422
        return 409
