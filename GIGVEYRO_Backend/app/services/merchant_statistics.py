import csv
import io
import uuid
from datetime import datetime

from app.repositories.invoice import InvoiceRepository
from app.repositories.withdrawal import WithdrawalRepository
from app.schemas.merchant_statistics import (
    MerchantInvoiceStatsRead,
    MerchantStatisticsRead,
    MerchantWithdrawalStatsRead,
)


class MerchantStatisticsService:
    def __init__(
        self, invoice_repository: InvoiceRepository, withdrawal_repository: WithdrawalRepository
    ):
        self._invoices = invoice_repository
        self._withdrawals = withdrawal_repository

    async def for_merchant(self, merchant_id: uuid.UUID) -> MerchantStatisticsRead:
        invoice_stats = await self._invoices.stats_for_merchant(merchant_id)
        withdrawal_stats = await self._withdrawals.stats_for_merchant(merchant_id)
        return MerchantStatisticsRead(
            invoices=MerchantInvoiceStatsRead(**invoice_stats),
            withdrawals=MerchantWithdrawalStatsRead(**withdrawal_stats),
        )

    async def invoices_csv(
        self, merchant_id: uuid.UUID, *, date_from: datetime | None, date_to: datetime | None
    ) -> str:
        invoices = await self._invoices.list_for_merchant_export(
            merchant_id, date_from=date_from, date_to=date_to
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "public_id",
                "amount",
                "status",
                "description",
                "external_reference",
                "created_at",
                "paid_at",
            ]
        )
        for invoice in invoices:
            writer.writerow(
                [
                    invoice.public_id,
                    format(invoice.amount, "f"),
                    invoice.status.value,
                    invoice.description or "",
                    invoice.external_reference or "",
                    invoice.created_at.isoformat(),
                    invoice.paid_at.isoformat() if invoice.paid_at else "",
                ]
            )
        return buffer.getvalue()
