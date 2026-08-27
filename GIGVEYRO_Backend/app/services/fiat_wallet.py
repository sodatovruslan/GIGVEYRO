import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from app.enums.account import UserRole
from app.enums.wallet import Currency, FiatLedgerEntryType
from app.models.account import Account
from app.models.fiat_wallet import FiatConversion, FiatLedgerEntry, FiatWalletBalance
from app.repositories.account import AccountRepository
from app.repositories.fiat_wallet import (
    FiatConversionRepository,
    FiatLedgerRepository,
    FiatWalletRepository,
)
from app.services.fiat_rate.conversion import FiatConversionRateService
from app.services.fiat_rate.models import FiatConversionQuote

_MONEY_QUANTUM = Decimal("0.00000001")


class FiatWalletNotFoundError(Exception):
    pass


class FiatWalletPermissionError(Exception):
    pass


class FiatWalletValidationError(Exception):
    pass


class FiatInsufficientBalanceError(Exception):
    pass


class FiatIdempotencyConflictError(Exception):
    pass


class FiatWalletService:
    def __init__(
        self,
        *,
        wallets: FiatWalletRepository,
        ledger: FiatLedgerRepository,
        conversions: FiatConversionRepository,
        accounts: AccountRepository,
        rates: FiatConversionRateService,
    ) -> None:
        self._wallets = wallets
        self._ledger = ledger
        self._conversions = conversions
        self._accounts = accounts
        self._rates = rates

    async def get_balances(self, account_id: uuid.UUID) -> list[FiatWalletBalance]:
        await self._require_user(account_id, active_required=False)
        existing = {item.currency: item for item in await self._wallets.list_balances(account_id)}
        now = datetime.now(UTC)
        return [
            existing.get(currency)
            or FiatWalletBalance(
                account_id=account_id,
                currency=currency,
                available=Decimal("0.00000000"),
                created_at=now,
                updated_at=now,
            )
            for currency in Currency.managed_fiat()
        ]

    async def allocate(
        self,
        *,
        actor: Account,
        target_account_id: uuid.UUID,
        currency: Currency,
        amount: Decimal,
        comment: str | None,
        idempotency_key: str,
    ) -> tuple[FiatLedgerEntry, bool]:
        self._require_owner(actor)
        self._validate_currency(currency)
        self._validate_positive(amount)
        await self._require_user(target_account_id, active_required=True)
        balances = await self._wallets.lock_balances(target_account_id)
        balance = balances[currency]
        existing = await self._ledger.by_actor_idempotency(actor.id, idempotency_key)
        if existing is not None:
            if (
                existing.type != FiatLedgerEntryType.OWNER_ALLOCATION
                or existing.amount != amount
                or existing.account_id != target_account_id
                or existing.currency != currency
                or existing.created_by_account_id != actor.id
            ):
                raise FiatIdempotencyConflictError("Idempotency key payload does not match")
            return existing, True

        before = balance.available
        balance.available = before + amount
        await self._wallets.save(balance)
        operation_id = uuid.uuid4()
        entry = await self._ledger.create(
            FiatLedgerEntry(
                balance_id=balance.id,
                account_id=target_account_id,
                currency=currency,
                type=FiatLedgerEntryType.OWNER_ALLOCATION,
                amount=amount,
                balance_before=before,
                balance_after=balance.available,
                reference_type="fiat_allocation",
                reference_id=operation_id,
                description=comment,
                idempotency_key=idempotency_key,
                created_by_account_id=actor.id,
            )
        )
        return entry, False

    async def preview(
        self, *, from_currency: Currency, to_currency: Currency, source_amount: Decimal
    ) -> tuple[Decimal, FiatConversionQuote]:
        self._validate_conversion(from_currency, to_currency, source_amount)
        quote = await self._rates.get_quote(from_currency, to_currency)
        destination = (source_amount * quote.rate).quantize(
            _MONEY_QUANTUM, rounding=ROUND_HALF_UP
        )
        if destination <= 0:
            raise FiatWalletValidationError("Destination amount rounds to zero")
        return destination, quote

    async def convert(
        self,
        *,
        actor: Account,
        target_account_id: uuid.UUID,
        from_currency: Currency,
        to_currency: Currency,
        source_amount: Decimal,
        comment: str | None,
        idempotency_key: str,
    ) -> tuple[FiatConversion, bool]:
        self._require_owner(actor)
        self._validate_conversion(from_currency, to_currency, source_amount)
        await self._require_user(target_account_id, active_required=True)

        existing = await self._conversions.by_actor_idempotency(actor.id, idempotency_key)
        if existing is not None:
            self._validate_conversion_replay(
                existing, target_account_id, from_currency, to_currency, source_amount
            )
            return existing, True

        destination_amount, quote = await self.preview(
            from_currency=from_currency,
            to_currency=to_currency,
            source_amount=source_amount,
        )
        balances = await self._wallets.lock_balances(target_account_id)
        existing = await self._conversions.by_actor_idempotency(actor.id, idempotency_key)
        if existing is not None:
            self._validate_conversion_replay(
                existing, target_account_id, from_currency, to_currency, source_amount
            )
            return existing, True

        source = balances[from_currency]
        destination = balances[to_currency]
        if source.available < source_amount:
            raise FiatInsufficientBalanceError("Insufficient managed fiat balance")

        source_before = source.available
        destination_before = destination.available
        source.available = source_before - source_amount
        destination.available = destination_before + destination_amount
        await self._wallets.save(source)
        await self._wallets.save(destination)

        conversion = await self._conversions.create(
            FiatConversion(
                account_id=target_account_id,
                initiated_by_account_id=actor.id,
                from_currency=from_currency,
                to_currency=to_currency,
                source_amount=source_amount,
                destination_amount=destination_amount,
                exchange_rate=quote.rate,
                source_balance_before=source_before,
                source_balance_after=source.available,
                destination_balance_before=destination_before,
                destination_balance_after=destination.available,
                rate_provider=quote.provider,
                rate_published_at=quote.published_at,
                rate_policy_version=quote.policy_version,
                rate_mode=quote.mode,
                comment=comment,
                idempotency_key=idempotency_key,
            )
        )
        await self._ledger.create(
            FiatLedgerEntry(
                balance_id=source.id,
                account_id=target_account_id,
                currency=from_currency,
                type=FiatLedgerEntryType.CONVERSION_DEBIT,
                amount=-source_amount,
                balance_before=source_before,
                balance_after=source.available,
                reference_type="fiat_conversion",
                reference_id=conversion.id,
                description=comment,
                idempotency_key=f"{idempotency_key}:debit",
                created_by_account_id=actor.id,
            )
        )
        await self._ledger.create(
            FiatLedgerEntry(
                balance_id=destination.id,
                account_id=target_account_id,
                currency=to_currency,
                type=FiatLedgerEntryType.CONVERSION_CREDIT,
                amount=destination_amount,
                balance_before=destination_before,
                balance_after=destination.available,
                reference_type="fiat_conversion",
                reference_id=conversion.id,
                description=comment,
                idempotency_key=f"{idempotency_key}:credit",
                created_by_account_id=actor.id,
            )
        )
        return conversion, False

    async def history(
        self,
        *,
        account_id: uuid.UUID | None,
        currency: Currency | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[FiatConversion], int]:
        if account_id is not None:
            await self._require_user(account_id, active_required=False)
        if currency is not None:
            self._validate_currency(currency)
        return await self._conversions.list_history(
            account_id=account_id,
            currency=currency,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )

    async def ledger(
        self, account_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[FiatLedgerEntry], int]:
        await self._require_user(account_id, active_required=False)
        return await self._ledger.list_for_account(account_id, limit=limit, offset=offset)

    async def _require_user(
        self, account_id: uuid.UUID, *, active_required: bool
    ) -> Account:
        account = await self._accounts.get_by_id(account_id)
        if account is None or account.role != UserRole.USER:
            raise FiatWalletNotFoundError("USER account not found")
        if active_required and not account.is_active:
            raise FiatWalletValidationError("Inactive USER balance cannot be modified")
        return account

    @staticmethod
    def _require_owner(actor: Account) -> None:
        if actor.role != UserRole.OWNER:
            raise FiatWalletPermissionError("Only OWNER can manage fiat balances")

    @staticmethod
    def _validate_currency(currency: Currency) -> None:
        if currency not in Currency.managed_fiat():
            raise FiatWalletValidationError("Only TJS and RUB are managed fiat currencies")

    @classmethod
    def _validate_conversion(
        cls, from_currency: Currency, to_currency: Currency, source_amount: Decimal
    ) -> None:
        cls._validate_currency(from_currency)
        cls._validate_currency(to_currency)
        if from_currency == to_currency:
            raise FiatWalletValidationError("Source and destination currencies must differ")
        cls._validate_positive(source_amount)

    @staticmethod
    def _validate_positive(amount: Decimal) -> None:
        if not amount.is_finite() or amount <= 0:
            raise FiatWalletValidationError("Amount must be a positive finite number")

    @staticmethod
    def _validate_conversion_replay(
        existing: FiatConversion,
        account_id: uuid.UUID,
        from_currency: Currency,
        to_currency: Currency,
        source_amount: Decimal,
    ) -> None:
        if (
            existing.account_id != account_id
            or existing.from_currency != from_currency
            or existing.to_currency != to_currency
            or existing.source_amount != source_amount
        ):
            raise FiatIdempotencyConflictError("Idempotency key payload does not match")
