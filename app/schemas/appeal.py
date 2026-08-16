import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums.account import UserRole
from app.enums.appeal import AppealReason, AppealResolution, AppealStatus
from app.enums.deal import DealStatus


class AppealCreate(BaseModel):
    reason_code: AppealReason
    message: str = Field(min_length=5, max_length=2000)


class AppealResolveRequest(BaseModel):
    resolution: AppealResolution
    owner_note: str = Field(min_length=3, max_length=2000)


class AppealReviewRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class AppealRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    public_id: str
    deal_id: uuid.UUID
    opened_by_account_id: uuid.UUID
    opened_by_role: UserRole
    reason_code: AppealReason
    message: str
    status: AppealStatus
    resolution: AppealResolution | None
    owner_note: str | None
    previous_deal_status: DealStatus
    resolved_by_account_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class AppealListResponse(BaseModel):
    items: list[AppealRead]
    total: int
    limit: int
    offset: int
