import uuid

from app.enums.invoice import InvoiceStatus
from app.enums.wallet import LedgerEntryType
from app.models.deposit import Deposit
from app.models.invoice import Invoice
from app.models.ledger import LedgerEntry
from app.models.webhook import WebhookDelivery
from app.repositories.deposit import DepositRepository
from app.repositories.invoice import InvoiceRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.webhook import WebhookDeliveryRepository
from app.schemas.invoice_timeline import (
    InvoiceTimelineRead,
    TimelineDepositRead,
    TimelineEventRead,
    TimelineLedgerEntryRead,
    TimelineWebhookDeliveryRead,
)
from app.services.invoice import InvoiceNotFoundError


class InvoiceTimelineService:
    """Pure read-only aggregation over Invoice + Deposit + LedgerEntry +
    WebhookDelivery - no new table, no financial side effects. Every event
    is derived from a real, existing timestamp column; a lifecycle branch
    with no dedicated timestamp (e.g. invoice/deposit EXPIRED) is reflected
    only via the entity's own `status` field, never a fabricated event."""

    def __init__(
        self,
        invoice_repository: InvoiceRepository,
        deposit_repository: DepositRepository,
        ledger_repository: LedgerRepository,
        webhook_delivery_repository: WebhookDeliveryRepository,
    ):
        self._invoices = invoice_repository
        self._deposits = deposit_repository
        self._ledger = ledger_repository
        self._webhook_deliveries = webhook_delivery_repository

    async def get_for_merchant(
        self, merchant_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> InvoiceTimelineRead:
        invoice = await self._invoices.get_by_id(invoice_id)
        if invoice is None or invoice.merchant_id != merchant_id:
            raise InvoiceNotFoundError()

        deposit = await self._deposits.get_by_invoice_id(invoice.id)

        ledger_entry: LedgerEntry | None = None
        if deposit is not None:
            ledger_entry = await self._ledger.get_by_reference(
                reference_type="deposit",
                reference_id=deposit.id,
                entry_type=LedgerEntryType.DEPOSIT_CREDIT,
            )

        deliveries = await self._webhook_deliveries.list_for_invoice(merchant_id, invoice.id)

        return InvoiceTimelineRead(
            invoice=invoice,
            deposit=TimelineDepositRead.model_validate(deposit) if deposit else None,
            ledger_entry=self._ledger_entry_view(ledger_entry),
            webhook_deliveries=[
                TimelineWebhookDeliveryRead.model_validate(delivery) for delivery in deliveries
            ],
            events=self._build_events(invoice, deposit, ledger_entry, deliveries),
        )

    @staticmethod
    def _ledger_entry_view(entry: LedgerEntry | None) -> TimelineLedgerEntryRead | None:
        if entry is None:
            return None
        return TimelineLedgerEntryRead(
            type=entry.type.value,
            amount=entry.amount,
            currency=entry.currency.value,
            created_at=entry.created_at,
        )

    @staticmethod
    def _build_events(
        invoice: Invoice,
        deposit: Deposit | None,
        ledger_entry: LedgerEntry | None,
        deliveries: list[WebhookDelivery],
    ) -> list[TimelineEventRead]:
        # Events are appended in fixed causal order and the final sort is
        # stable, so ties (e.g. deposit.credited_at == ledger_entry.created_at
        # to the microsecond) always resolve in this same order - that is
        # what makes the output deterministic, not the timestamps alone.
        events: list[TimelineEventRead] = [
            TimelineEventRead(type="invoice.created", at=invoice.created_at, data={}),
        ]

        if deposit is not None:
            if deposit.detected_at is not None:
                events.append(
                    TimelineEventRead(
                        type="deposit.detected",
                        at=deposit.detected_at,
                        data={"tx_hash": deposit.tx_hash},
                    )
                )
            if deposit.confirmed_at is not None:
                events.append(
                    TimelineEventRead(
                        type="deposit.confirmed",
                        at=deposit.confirmed_at,
                        data={
                            "confirmations": deposit.confirmations,
                            "required_confirmations": deposit.required_confirmations,
                        },
                    )
                )
            if deposit.credited_at is not None:
                events.append(
                    TimelineEventRead(
                        type="deposit.credited",
                        at=deposit.credited_at,
                        data={},
                    )
                )
            if deposit.failed_at is not None:
                events.append(
                    TimelineEventRead(
                        type="deposit.failed",
                        at=deposit.failed_at,
                        data={"status": deposit.status.value},
                    )
                )

        if ledger_entry is not None:
            events.append(
                TimelineEventRead(
                    type="invoice.balance_credited",
                    at=ledger_entry.created_at,
                    data={"amount": format(ledger_entry.amount, "f")},
                )
            )

        if invoice.status == InvoiceStatus.PAID and invoice.paid_at is not None:
            events.append(TimelineEventRead(type="invoice.paid", at=invoice.paid_at, data={}))

        if invoice.status == InvoiceStatus.CANCELLED and invoice.cancelled_at is not None:
            events.append(
                TimelineEventRead(type="invoice.cancelled", at=invoice.cancelled_at, data={})
            )

        for delivery in deliveries:
            events.append(
                TimelineEventRead(
                    type=f"webhook.{delivery.status.value}",
                    at=delivery.created_at,
                    data={
                        "webhook_id": str(delivery.webhook_id),
                        "attempts": delivery.attempts,
                        "max_attempts": delivery.max_attempts,
                        "last_response_status": delivery.last_response_status,
                        "delivered_at": (
                            delivery.delivered_at.isoformat() if delivery.delivered_at else None
                        ),
                    },
                )
            )

        events.sort(key=lambda event: event.at)
        return events
