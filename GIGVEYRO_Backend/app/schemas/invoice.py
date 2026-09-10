import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums.invoice import InvoiceStatus
from app.schemas.common import Money


class InvoiceCreate(BaseModel):
    amount: Money = Field(gt=0)
    description: str | None = Field(default=None, max_length=500)
    external_reference: str | None = Field(default=None, max_length=255)


class InvoiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    public_id: str
    merchant_id: uuid.UUID
    amount: Money
    description: str | None
    external_reference: str | None
    deposit_address: str
    status: InvoiceStatus
    expires_at: datetime
    paid_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvoiceListResponse(BaseModel):
    items: list[InvoiceRead]
    total: int
    limit: int
    offset: int


class PublicInvoiceRead(BaseModel):
    """Customer-facing subset shown on the unauthenticated payment page -
    no merchant identity or internal fields (store_name is the one
    merchant-controlled exception, set via the Store Settings page)."""

    model_config = ConfigDict(from_attributes=True)

    public_id: str
    amount: Money
    description: str | None
    deposit_address: str
    status: InvoiceStatus
    expires_at: datetime
    store_name: str | None = None
