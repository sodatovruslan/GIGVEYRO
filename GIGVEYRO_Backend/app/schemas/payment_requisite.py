import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.enums.payment_requisite import PaymentRequisiteType

MIN_CARD_DIGITS = 8
MAX_CARD_DIGITS = 19

_NON_DIGIT_SEPARATORS = re.compile(r"[\s-]")


def canonicalize_card_number(raw: str) -> str:
    digits = _NON_DIGIT_SEPARATORS.sub("", raw)
    if not digits.isdigit():
        raise ValueError("card number must contain only digits, spaces, or hyphens")
    if not (MIN_CARD_DIGITS <= len(digits) <= MAX_CARD_DIGITS):
        raise ValueError(f"card number must be {MIN_CARD_DIGITS}-{MAX_CARD_DIGITS} digits")
    return digits


def mask_card_number(digits: str) -> str:
    last_four = digits[-4:]
    remaining = len(digits) - 4
    masked_groups = -(-remaining // 4)  # ceil division
    return " ".join(["****"] * masked_groups + [last_four])


class PaymentRequisiteCreate(BaseModel):
    type: PaymentRequisiteType = PaymentRequisiteType.BANK_CARD
    bank_name: str = Field(min_length=1, max_length=255)
    holder_name: str = Field(min_length=1, max_length=255)
    card_number: str = Field(min_length=1, max_length=32)
    phone_number: str | None = Field(default=None, max_length=32)

    @field_validator("card_number")
    @classmethod
    def _canonicalize_card_number(cls, value: str) -> str:
        return canonicalize_card_number(value)


class PaymentRequisiteUpdate(BaseModel):
    bank_name: str | None = Field(default=None, min_length=1, max_length=255)
    holder_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone_number: str | None = Field(default=None, max_length=32)


class PaymentRequisiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: PaymentRequisiteType
    bank_name: str
    holder_name: str
    # Never serialized directly - only masked_card_number leaves this
    # process. Present here purely so the computed field below can read it.
    card_number: str = Field(exclude=True, repr=False)
    phone_number: str | None
    is_active: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def masked_card_number(self) -> str:
        return mask_card_number(self.card_number)
