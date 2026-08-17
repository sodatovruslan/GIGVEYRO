import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.enums.account import UserRole
from app.enums.appeal import AppealReason, AppealResolution, AppealStatus
from app.enums.deal import DealStatus


class DealAppeal(Base):
    __tablename__ = "deal_appeals"
    __table_args__ = (
        Index(
            "uq_deal_appeals_active_deal",
            "deal_id",
            unique=True,
            postgresql_where=text("status IN ('open', 'under_review')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    public_id: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)

    deal_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("deals.id"), nullable=False, index=True
    )
    opened_by_account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    opened_by_role: Mapped[UserRole] = mapped_column(
        SAEnum(
            UserRole,
            values_callable=lambda enum: [member.value for member in enum],
            name="user_role",
        ),
        nullable=False,
    )

    reason_code: Mapped[AppealReason] = mapped_column(
        SAEnum(
            AppealReason,
            values_callable=lambda enum: [member.value for member in enum],
            name="appeal_reason",
        ),
        nullable=False,
        index=True,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[AppealStatus] = mapped_column(
        SAEnum(
            AppealStatus,
            values_callable=lambda enum: [member.value for member in enum],
            name="appeal_status",
        ),
        nullable=False,
        index=True,
        default=AppealStatus.OPEN,
    )
    resolution: Mapped[AppealResolution | None] = mapped_column(
        SAEnum(
            AppealResolution,
            values_callable=lambda enum: [member.value for member in enum],
            name="appeal_resolution",
        ),
        nullable=True,
    )
    owner_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    previous_deal_status: Mapped[DealStatus] = mapped_column(
        SAEnum(
            DealStatus,
            values_callable=lambda enum: [member.value for member in enum],
            name="deal_status",
        ),
        nullable=False,
    )

    resolved_by_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
