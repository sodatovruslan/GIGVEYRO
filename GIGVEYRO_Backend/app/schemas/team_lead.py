import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import Money


class TeamMemberRead(BaseModel):
    """Deliberately minimal - identity and status only. Never the member's
    own wallet balance or personal financial data, which belongs to the
    USER, not their Team Lead."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    full_name: str
    is_active: bool
    created_at: datetime


class TeamMemberListResponse(BaseModel):
    items: list[TeamMemberRead]
    total: int
    limit: int
    offset: int


class TeamLeadDashboardRead(BaseModel):
    profit_available: Money
    profit_pending_withdrawal: Money
    team_size: int
    deal_count: int
    deal_volume: Money
