import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.config import settings
from app.enums.account import UserRole
from app.enums.deposit import DepositAsset, DepositNetwork, DepositStatus
from app.enums.invoice import InvoiceStatus
from app.models.account import Account
from app.models.deposit import Deposit
from app.models.invoice import Invoice
from app.repositories.deposit import DepositRepository
from app.repositories.invoice import InvoiceRepository
from app.services.deposit import generate_deposit_public_id, transition_deposit
from app.services.deposit_provider import CryptoDepositProvider


class InvoiceNotFoundError(Exception):
    """Covers a missing invoice and one that exists but isn't visible to the caller."""


class InvoiceNotAllowedError(Exception):
    """Raised when a non-MERCHANT account attempts to create an invoice."""


class InvoiceNotCancellableError(Exception):
    """Raised when cancel is attempted on an invoice that isn't PENDING_PAYMENT."""


class InvalidInvoiceTransitionError(Exception):
    """Raised when an invoice status change isn't in ALLOWED_TRANSITIONS."""


ALLOWED_TRANSITIONS: dict[InvoiceStatus, set[InvoiceStatus]] = {
    InvoiceStatus.PENDING_PAYMENT: {
        InvoiceStatus.PAID,
        InvoiceStatus.EXPIRED,
        InvoiceStatus.CANCELLED,
    },
    InvoiceStatus.PAID: set(),
    InvoiceStatus.EXPIRED: set(),
    InvoiceStatus.CANCELLED: set(),
}


def generate_invoice_public_id() -> str:
    return f"INV-{secrets.token_hex(4).upper()}"


def transition_invoice(invoice: Invoice, new_status: InvoiceStatus) -> None:
    if new_status not in ALLOWED_TRANSITIONS.get(invoice.status, set()):
        raise InvalidInvoiceTransitionError(
            f"cannot transition invoice from {invoice.status} to {new_status}"
        )
    invoice.status = new_status
    if new_status == InvoiceStatus.PAID:
        invoice.paid_at = datetime.now(UTC)
    elif new_status == InvoiceStatus.CANCELLED:
        invoice.cancelled_at = datetime.now(UTC)


class InvoiceService:
    def __init__(
        self,
        invoice_repository: InvoiceRepository,
        deposit_repository: DepositRepository,
        provider: CryptoDepositProvider,
    ):
        self._invoices = invoice_repository
        self._deposits = deposit_repository
        self._provider = provider

    async def create_invoice(
        self,
        merchant: Account,
        *,
        amount: Decimal,
        description: str | None,
        external_reference: str | None,
    ) -> Invoice:
        if merchant.role != UserRole.MERCHANT:
            raise InvoiceNotAllowedError("only MERCHANT accounts can create invoices")

        expires_at = datetime.now(UTC) + timedelta(minutes=settings.INVOICE_TTL_MINUTES)
        deposit_address = self._provider.get_deposit_address()

        invoice = Invoice(
            public_id=generate_invoice_public_id(),
            merchant_id=merchant.id,
            amount=amount,
            description=description,
            external_reference=external_reference,
            deposit_address=deposit_address,
            status=InvoiceStatus.PENDING_PAYMENT,
            expires_at=expires_at,
        )
        invoice = await self._invoices.create(invoice)

        deposit = Deposit(
            public_id=generate_deposit_public_id(),
            account_id=merchant.id,
            invoice_id=invoice.id,
            network=DepositNetwork.TRC20,
            asset=DepositAsset.USDT,
            expected_amount=amount,
            deposit_address=deposit_address,
            confirmations=0,
            required_confirmations=settings.TRC20_REQUIRED_CONFIRMATIONS,
            status=DepositStatus.WAITING,
            expires_at=expires_at,
        )
        await self._deposits.create(deposit)

        return invoice

    async def get_for_merchant(self, merchant_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
        invoice = await self._get_or_raise(invoice_id)
        if invoice.merchant_id != merchant_id:
            raise InvoiceNotFoundError()
        return await self._expire_if_needed(invoice)

    async def list_for_merchant(
        self, merchant_id: uuid.UUID, *, status: InvoiceStatus | None, limit: int, offset: int
    ) -> tuple[list[Invoice], int]:
        await self._invoices.expire_stale_pending()
        items = await self._invoices.list_for_merchant(
            merchant_id, status=status, limit=limit, offset=offset
        )
        total = await self._invoices.count_for_merchant(merchant_id, status=status)
        return items, total

    async def cancel_invoice(self, merchant_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
        invoice = await self._invoices.get_by_id_for_update(invoice_id)
        if invoice is None or invoice.merchant_id != merchant_id:
            raise InvoiceNotFoundError()
        if invoice.status != InvoiceStatus.PENDING_PAYMENT:
            raise InvoiceNotCancellableError("only a pending invoice can be cancelled")

        linked_deposit = await self._deposits.get_by_invoice_id(invoice.id)
        if linked_deposit is not None and linked_deposit.status == DepositStatus.WAITING:
            transition_deposit(linked_deposit, DepositStatus.FAILED)
            await self._deposits.save(linked_deposit)

        transition_invoice(invoice, InvoiceStatus.CANCELLED)
        return await self._invoices.save(invoice)

    async def get_by_public_id(self, public_id: str) -> Invoice:
        invoice = await self._invoices.get_by_public_id(public_id)
        if invoice is None:
            raise InvoiceNotFoundError()
        return await self._expire_if_needed(invoice)

    async def _get_or_raise(self, invoice_id: uuid.UUID) -> Invoice:
        invoice = await self._invoices.get_by_id(invoice_id)
        if invoice is None:
            raise InvoiceNotFoundError()
        return invoice

    async def _expire_if_needed(self, invoice: Invoice) -> Invoice:
        if (
            invoice.status == InvoiceStatus.PENDING_PAYMENT
            and invoice.expires_at <= datetime.now(UTC)
        ):
            transition_invoice(invoice, InvoiceStatus.EXPIRED)
            await self._invoices.save(invoice)
        return invoice
