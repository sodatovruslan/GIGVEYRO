import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RealtimeEventName(StrEnum):
    DEAL_CREATED = "deal.created"
    DEAL_ACCEPTED = "deal.accepted"
    DEAL_COMPLETED = "deal.completed"
    DEAL_RELEASED = "deal.released"
    DEAL_EXPIRED = "deal.expired"
    DEAL_DISPUTED = "deal.disputed"
    FIAT_ALLOCATED = "fiat.allocated"
    FIAT_CONVERTED = "fiat.converted"
    PAYOUT_UPDATED = "payout.updated"
    WITHDRAWAL_UPDATED = "withdrawal.updated"


class RealtimeEvent(BaseModel):
    version: Literal[1] = 1
    id: uuid.UUID
    event: RealtimeEventName
    entity_id: uuid.UUID
    occurred_at: datetime
    data: dict[str, Any] = Field(default_factory=dict)
