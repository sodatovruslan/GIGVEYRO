import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.enums.deposit import DepositStatus
from app.enums.webhook import WebhookDeliveryStatus
from app.schemas.common import Money
from app.schemas.invoice import InvoiceRead


class TimelineDepositRead(BaseModel):
    """Merchant-safe subset of Deposit - excludes account_id (internal),
    provider_event_id (scanner dedup key) and public_id/wallet linkage
    beyond what's needed to explain the payment."""

    model_config = ConfigDict(from_attributes=True)

    public_id: str
    status: DepositStatus
    expected_amount: Money
    received_amount: Money | None
    credited_amount: Money | None
    tx_hash: str | None
    confirmations: int
    required_confirmations: int
    detected_at: datetime | None
    confirmed_at: datetime | None
    credited_at: datetime | None
    failed_at: datetime | None


class TimelineLedgerEntryRead(BaseModel):
    """Deliberately excludes available_before/after and every other
    balance-snapshot column - only the resulting credit amount is shown."""

    type: str
    amount: Money
    currency: str
    created_at: datetime


class TimelineWebhookDeliveryRead(BaseModel):
    """One row per WebhookDelivery record. The model stores only the
    current aggregate state of a delivery (attempts/last_response_status/
    last_error), not a per-attempt history, so this reflects that same
    aggregate - it does not fabricate individual attempt timestamps."""

    model_config = ConfigDict(from_attributes=True)

    webhook_id: uuid.UUID
    event_type: str
    status: WebhookDeliveryStatus
    attempts: int
    max_attempts: int
    last_response_status: int | None
    last_error: str | None
    next_attempt_at: datetime | None
    created_at: datetime
    delivered_at: datetime | None


class TimelineEventRead(BaseModel):
    type: str
    at: datetime
    data: dict[str, Any] = {}


class InvoiceTimelineRead(BaseModel):
    invoice: InvoiceRead
    deposit: TimelineDepositRead | None
    ledger_entry: TimelineLedgerEntryRead | None
    webhook_deliveries: list[TimelineWebhookDeliveryRead]
    events: list[TimelineEventRead]
