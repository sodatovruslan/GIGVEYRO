import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.enums.account import UserRole
from app.enums.deposit import CorrelationStatus, DepositAsset, DepositNetwork, DepositStatus
from app.enums.notification import NotificationType
from app.models.account import Account
from app.models.deposit import Deposit, UnmatchedTransfer
from app.repositories.account import AccountRepository
from app.repositories.deposit import DepositRepository
from app.services.audit import AuditService
from app.services.deposit_provider import CryptoDepositProvider
from app.services.notification import NotificationService
from app.services.wallet import WalletService

logger = logging.getLogger(__name__)

_TERMINAL_TIMESTAMP_FIELD = {
    DepositStatus.CONFIRMED: "confirmed_at",
    DepositStatus.CREDITED: "credited_at",
    DepositStatus.FAILED: "failed_at",
}

ALLOWED_TRANSITIONS: dict[DepositStatus, set[DepositStatus]] = {
    DepositStatus.WAITING: {
        DepositStatus.DETECTED,
        DepositStatus.EXPIRED,
        DepositStatus.FAILED,
        DepositStatus.AMOUNT_MISMATCH,
    },
    DepositStatus.DETECTED: {
        DepositStatus.CONFIRMING,
        DepositStatus.CONFIRMED,
        DepositStatus.FAILED,
    },
    DepositStatus.CONFIRMING: {DepositStatus.CONFIRMED, DepositStatus.FAILED},
    DepositStatus.CONFIRMED: {DepositStatus.CREDITED},
    DepositStatus.CREDITED: set(),
    DepositStatus.EXPIRED: set(),
    DepositStatus.FAILED: set(),
    DepositStatus.AMOUNT_MISMATCH: set(),
}


class DepositNotFoundError(Exception):
    """Covers a missing deposit and one that exists but isn't visible to the caller."""


class DepositNotAllowedError(Exception):
    """Raised when a non-USER account attempts to create a deposit intent."""


class InvalidDepositTransitionError(Exception):
    """Raised when a deposit status change isn't in ALLOWED_TRANSITIONS."""


class InvalidTransactionError(Exception):
    """Raised when an ingested transaction event fails a structural check."""


class DuplicateTransactionError(Exception):
    """Raised when a tx_hash has already been used by a different deposit."""


def generate_deposit_public_id() -> str:
    return f"DEP-{secrets.token_hex(4).upper()}"


def transition_deposit(deposit: Deposit, new_status: DepositStatus) -> None:
    if new_status not in ALLOWED_TRANSITIONS.get(deposit.status, set()):
        raise InvalidDepositTransitionError(
            f"cannot transition deposit from {deposit.status} to {new_status}"
        )
    deposit.status = new_status
    timestamp_field = _TERMINAL_TIMESTAMP_FIELD.get(new_status)
    if timestamp_field is not None:
        setattr(deposit, timestamp_field, datetime.now(UTC))


class DepositService:
    def __init__(
        self,
        deposit_repository: DepositRepository,
        account_repository: AccountRepository,
        wallet_service: WalletService,
        provider: CryptoDepositProvider,
        notification_service: NotificationService | None = None,
        audit_service: AuditService | None = None,
    ):
        self._deposits = deposit_repository
        self._accounts = account_repository
        self._wallet_service = wallet_service
        self._provider = provider
        self._notifications = notification_service
        self._audit = audit_service

    async def _audit_deposit(self, deposit: Deposit, action: str) -> None:
        if self._audit is not None:
            await self._audit.log_action(
                action=action,
                entity_type="deposit",
                entity_id=str(deposit.id),
                actor_account_id=None,
                actor_role="system",
            )

    async def create_deposit_intent(self, account: Account, *, amount: Decimal) -> Deposit:
        if account.role != UserRole.USER:
            raise DepositNotAllowedError("only USER accounts can create deposits")

        expires_at = datetime.now(UTC) + timedelta(minutes=settings.DEPOSIT_TTL_MINUTES)
        deposit_address = self._provider.get_deposit_address()

        last_error: IntegrityError | None = None
        for _ in range(3):
            deposit = Deposit(
                public_id=generate_deposit_public_id(),
                account_id=account.id,
                network=DepositNetwork.TRC20,
                asset=DepositAsset.USDT,
                expected_amount=amount,
                deposit_address=deposit_address,
                confirmations=0,
                required_confirmations=settings.TRC20_REQUIRED_CONFIRMATIONS,
                status=DepositStatus.WAITING,
                expires_at=expires_at,
            )
            try:
                return await self._deposits.create(deposit)
            except IntegrityError as exc:
                last_error = exc
        raise last_error

    async def get_own(self, account_id: uuid.UUID, deposit_id: uuid.UUID) -> Deposit:
        deposit = await self._get_or_raise(deposit_id)
        if deposit.account_id != account_id:
            raise DepositNotFoundError()
        return await self._expire_if_needed(deposit)

    async def list_own(
        self, account_id: uuid.UUID, *, status: DepositStatus | None, limit: int, offset: int
    ) -> tuple[list[Deposit], int]:
        await self._deposits.expire_stale_waiting()
        items = await self._deposits.list_for_account(
            account_id, status=status, limit=limit, offset=offset
        )
        total = await self._deposits.count_for_account(account_id, status=status)
        return items, total

    async def get_for_owner(self, deposit_id: uuid.UUID) -> Deposit:
        deposit = await self._get_or_raise(deposit_id)
        return await self._expire_if_needed(deposit)

    async def list_for_owner(
        self,
        *,
        status: DepositStatus | None,
        account_id: uuid.UUID | None,
        search: str | None,
        tx_hash: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Deposit], int]:
        await self._deposits.expire_stale_waiting()
        items = await self._deposits.list_all(
            status=status,
            account_id=account_id,
            search=search,
            tx_hash=tx_hash,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        total = await self._deposits.count_all(
            status=status,
            account_id=account_id,
            search=search,
            tx_hash=tx_hash,
            date_from=date_from,
            date_to=date_to,
        )
        return items, total

    async def get_unmatched_for_owner(self, transfer_id: uuid.UUID) -> UnmatchedTransfer:
        transfer = await self._deposits.get_unmatched_by_id(transfer_id)
        if transfer is None:
            raise DepositNotFoundError()
        return transfer

    async def list_unmatched_for_owner(
        self,
        *,
        correlation_status: CorrelationStatus | None,
        tx_hash: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        min_amount: Decimal | None,
        max_amount: Decimal | None,
        limit: int,
        offset: int,
    ) -> tuple[list[UnmatchedTransfer], int]:
        items = await self._deposits.list_unmatched(
            correlation_status=correlation_status,
            tx_hash=tx_hash,
            date_from=date_from,
            date_to=date_to,
            min_amount=min_amount,
            max_amount=max_amount,
            limit=limit,
            offset=offset,
        )
        total = await self._deposits.count_unmatched(
            correlation_status=correlation_status,
            tx_hash=tx_hash,
            date_from=date_from,
            date_to=date_to,
            min_amount=min_amount,
            max_amount=max_amount,
        )
        return items, total

    async def scan_and_correlate_deposits(self, *, min_timestamp_ms: int | None = None) -> int:
        """Scan recent on-chain transfers and correlate them with active deposit intents."""
        await self._deposits.expire_stale_waiting()
        address = self._provider.get_deposit_address()
        recent_txs = await self._provider.fetch_recent_transactions(
            address, min_timestamp_ms=min_timestamp_ms
        )

        processed_count = 0
        for tx in recent_txs:
            if not tx.is_success or not tx.is_finalized:
                continue
            if tx.asset_contract != settings.USDT_TRC20_CONTRACT_ADDRESS:
                continue
            if tx.to_address != address:
                continue

            existing_dep = await self._deposits.get_by_provider_event_id(tx.provider_event_id)
            if existing_dep is None:
                # Compatibility with deposits recorded before provider-event identity existed.
                existing_dep = await self._deposits.get_legacy_by_tx_hash(tx.tx_hash)
            if existing_dep:
                await self.ingest_transaction_event(
                    deposit_id=existing_dep.id,
                    tx_hash=tx.tx_hash,
                    amount=tx.amount,
                    confirmations=tx.confirmations,
                    network=tx.network,
                    asset=DepositAsset.USDT,
                    destination_address=tx.to_address,
                    provider_event_id=tx.provider_event_id,
                )
                processed_count += 1
                continue

            existing_unmatched = await self._deposits.get_unmatched_by_provider_event_id(
                tx.provider_event_id
            )
            if existing_unmatched is None:
                existing_unmatched = await self._deposits.get_legacy_unmatched_by_tx_hash(
                    tx.tx_hash
                )
            if existing_unmatched:
                continue

            waiting_deposits = await self._deposits.list_all(
                status=DepositStatus.WAITING,
                account_id=None,
                search=None,
                tx_hash=None,
                date_from=None,
                date_to=None,
                limit=100,
                offset=0,
            )

            matching_deps = [d for d in waiting_deposits if d.expected_amount == tx.amount]

            if len(matching_deps) == 0:
                await self._deposits.create_unmatched_transfer(
                    UnmatchedTransfer(
                        tx_hash=tx.tx_hash,
                        provider_event_id=tx.provider_event_id,
                        from_address=tx.from_address,
                        to_address=tx.to_address,
                        amount=tx.amount,
                        asset_contract=tx.asset_contract,
                        correlation_status=CorrelationStatus.UNMATCHED,
                        reason="No WAITING Deposit Intent matching amount found",
                    )
                )
            elif len(matching_deps) > 1:
                await self._deposits.create_unmatched_transfer(
                    UnmatchedTransfer(
                        tx_hash=tx.tx_hash,
                        provider_event_id=tx.provider_event_id,
                        from_address=tx.from_address,
                        to_address=tx.to_address,
                        amount=tx.amount,
                        asset_contract=tx.asset_contract,
                        correlation_status=CorrelationStatus.AMBIGUOUS,
                        reason=(
                            f"Ambiguous match: {len(matching_deps)} WAITING deposits "
                            "share the same amount"
                        ),
                    )
                )
            else:
                dep = matching_deps[0]
                try:
                    await self.ingest_transaction_event(
                        deposit_id=dep.id,
                        tx_hash=tx.tx_hash,
                        amount=tx.amount,
                        confirmations=tx.confirmations,
                        network=tx.network,
                        asset=DepositAsset.USDT,
                        destination_address=tx.to_address,
                        provider_event_id=tx.provider_event_id,
                    )
                    processed_count += 1
                except (InvalidTransactionError, DuplicateTransactionError) as exc:
                    logger.warning("Deposit correlation error for tx %s: %s", tx.tx_hash, exc)

        return processed_count

    async def ingest_transaction_event(
        self,
        deposit_id: uuid.UUID,
        *,
        tx_hash: str,
        amount: Decimal,
        confirmations: int,
        network: DepositNetwork,
        asset: DepositAsset,
        destination_address: str,
        provider_event_id: str | None = None,
    ) -> Deposit:
        deposit = await self._deposits.get_by_id_for_update(deposit_id)
        if deposit is None:
            raise DepositNotFoundError()

        if deposit.status in (
            DepositStatus.CREDITED,
            DepositStatus.EXPIRED,
            DepositStatus.FAILED,
            DepositStatus.AMOUNT_MISMATCH,
        ):
            return deposit

        if network != DepositNetwork.TRC20 or asset != DepositAsset.USDT:
            raise InvalidTransactionError("unsupported network or asset")
        if destination_address != deposit.deposit_address:
            raise InvalidTransactionError("transaction destination does not match this deposit")
        if not tx_hash:
            raise InvalidTransactionError("tx_hash is required")
        if not amount.is_finite() or amount <= 0:
            raise InvalidTransactionError("invalid amount")

        normalized_event_id = provider_event_id or f"legacy:{tx_hash}:0"
        if deposit.tx_hash is None:
            existing = await self._deposits.get_by_provider_event_id(normalized_event_id)
            if existing is not None:
                raise DuplicateTransactionError("this provider event has already been used")

            deposit.tx_hash = tx_hash
            deposit.provider_event_id = normalized_event_id
            deposit.received_amount = amount
            deposit.detected_at = datetime.now(UTC)
            deposit.confirmations = max(deposit.confirmations, confirmations)

            if amount != deposit.expected_amount:
                transition_deposit(deposit, DepositStatus.AMOUNT_MISMATCH)
                saved = await self._deposits.save(deposit)
                await self._audit_deposit(saved, "deposit.amount_mismatch")
                return saved

            transition_deposit(deposit, DepositStatus.DETECTED)
        else:
            if deposit.tx_hash != tx_hash:
                raise InvalidTransactionError(
                    "tx_hash does not match the transaction already recorded for this deposit"
                )
            if deposit.provider_event_id not in {None, normalized_event_id}:
                raise InvalidTransactionError(
                    "provider event does not match the event already recorded for this deposit"
                )
            deposit.provider_event_id = normalized_event_id
            deposit.confirmations = max(deposit.confirmations, confirmations)

        if deposit.status == DepositStatus.DETECTED and deposit.confirmations > 0:
            transition_deposit(deposit, DepositStatus.CONFIRMING)

        if deposit.confirmations >= deposit.required_confirmations and deposit.status in (
            DepositStatus.DETECTED,
            DepositStatus.CONFIRMING,
        ):
            transition_deposit(deposit, DepositStatus.CONFIRMED)
            deposit = await self._deposits.save(deposit)
            return await self._credit(deposit)

        return await self._deposits.save(deposit)

    async def _credit(self, deposit: Deposit) -> Deposit:
        await self._wallet_service.credit_deposit(
            account_id=deposit.account_id,
            amount=deposit.received_amount,
            deposit_id=deposit.id,
        )

        deposit.credited_amount = deposit.received_amount
        transition_deposit(deposit, DepositStatus.CREDITED)
        saved = await self._deposits.save(deposit)

        if self._notifications is not None:
            await self._notifications.emit_notification(
                deposit.account_id,
                NotificationType.DEPOSIT_CONFIRMED,
                title="Deposit credited",
                message=(
                    f"Deposit {deposit.public_id} for {deposit.credited_amount} "
                    "USDT was credited"
                ),
                payload={"deposit_id": str(deposit.id)},
                dedupe_key=f"deposit_credited:{deposit.id}",
            )

        await self._audit_deposit(saved, "deposit.credited")

        return saved

    async def _get_or_raise(self, deposit_id: uuid.UUID) -> Deposit:
        deposit = await self._deposits.get_by_id(deposit_id)
        if deposit is None:
            raise DepositNotFoundError()
        return deposit

    async def _expire_if_needed(self, deposit: Deposit) -> Deposit:
        if deposit.status == DepositStatus.WAITING and deposit.expires_at <= datetime.now(UTC):
            transition_deposit(deposit, DepositStatus.EXPIRED)
            await self._deposits.save(deposit)
        return deposit
