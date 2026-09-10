import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MerchantProfileUpdate(BaseModel):
    store_name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    support_contact: str | None = Field(default=None, max_length=255)


class MerchantProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    merchant_id: uuid.UUID
    store_name: str | None
    description: str | None
    support_contact: str | None
    created_at: datetime
    updated_at: datetime
