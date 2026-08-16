import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.enums.account import UserRole
from app.enums.deposit import DepositAsset, DepositNetwork, DepositStatus
from app.models.account import Account
from app.models.deposit import Deposit
from app.repositories.account import AccountRepository
from app.repositories.deposit import DepositRepository
from app.services.deposit_provider import CryptoDepositProvider
from app.services.wallet import WalletService

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
    """Covers a missing deposit and one that exists but isn't visible to
    the caller (wrong account) - one safe 404 either way."""


class DepositNotAllowedError(Exception):
    """Raised when a non-USER account attempts to create a deposit intent."""


class InvalidDepositTransitionError(Exception):
    """Raised when a deposit status change isn't in ALLOWED_TRANSITIONS."""


class InvalidTransactionError(Exception):
    """Raised when an ingested transaction event fails a structural check
    (wrong network/asset/destination, missing tx_hash, bad amount)."""


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
    ):
        self._deposits = deposit_repository
        self._accounts = account_repository
        self._wallet_service = wallet_service
        self._provider = provider

    # -- USER ---------------------------------------------------------------

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
        raise last_error  # pragma: no cover - astronomically unlikely

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

    # -- OWNER (read-only) ------------------------------------------------

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

    # -- transaction ingestion (fed by the DEV-only simulate endpoint today,
    # a real chain-watching worker in a later stage) ----------------------

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
    ) -> Deposit:
        deposit = await self._deposits.get_by_id_for_update(deposit_id)
        if deposit is None:
            raise DepositNotFoundError()

        # Idempotent no-op once the deposit has reached a final state -
        # a replayed/duplicate event must never re-trigger anything.
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

        if deposit.tx_hash is None:
            existing = await self._deposits.get_by_tx_hash(tx_hash)
            if existing is not None:
                raise DuplicateTransactionError("this transaction has already been used")

            deposit.tx_hash = tx_hash
            deposit.received_amount = amount
            deposit.detected_at = datetime.now(UTC)
            deposit.confirmations = max(deposit.confirmations, confirmations)

            if amount != deposit.expected_amount:
                transition_deposit(deposit, DepositStatus.AMOUNT_MISMATCH)
                return await self._deposits.save(deposit)

            transition_deposit(deposit, DepositStatus.DETECTED)
        else:
            if deposit.tx_hash != tx_hash:
                raise InvalidTransactionError(
                    "tx_hash does not match the transaction already recorded for this deposit"
                )
            # Never let a stale/replayed lower confirmation count regress
            # what we've already observed.
            deposit.confirmations = max(deposit.confirmations, confirmations)

        if deposit.status == DepositStatus.DETECTED and deposit.confirmations > 0:
            transition_deposit(deposit, DepositStatus.CONFIRMING)

        if (
            deposit.confirmations >= deposit.required_confirmations
            and deposit.status in (DepositStatus.DETECTED, DepositStatus.CONFIRMING)
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
        return await self._deposits.save(deposit)

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
