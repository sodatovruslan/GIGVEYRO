from pydantic import BaseModel, ConfigDict, Field

from app.enums.wallet import Currency
from app.schemas.common import Money


class WalletRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    currency: Currency
    available_balance: Money
    insurance_balance: Money
    frozen_balance: Money


class AllocateRequest(BaseModel):
    amount: Money = Field(gt=0)
    description: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=255)


class InsuranceAdjustRequest(BaseModel):
    amount: Money = Field(description="Positive to increase, negative to decrease")
    description: str | None = Field(default=None, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=255)


class ManualAdjustRequest(BaseModel):
    amount: Money = Field(description="Positive to credit, negative to debit")
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=255)
