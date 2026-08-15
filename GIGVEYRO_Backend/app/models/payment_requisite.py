import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.enums.payment_requisite import PaymentRequisiteType


class PaymentRequisite(Base):
    """A USER's external payout method (fiat card/wallet), separate from
    UserWallet (GIGVEYRO's internal balances). Card data storage note:
    `card_number` is stored as plaintext canonical digits in this MVP
    stage - see the Stage 6 report for the production encryption-at-rest
    requirement this defers.
    """

    __tablename__ = "payment_requisites"
    __table_args__ = (
        CheckConstraint(
            "NOT (is_archived AND is_active)", name="ck_payment_requisites_archived_not_active"
        ),
        CheckConstraint("card_number <> ''", name="ck_payment_requisites_card_number_not_empty"),
        # A given account can't have two non-archived requisites with the
        # same card number - archived ones are excluded so a previously
        # archived card can legitimately be re-added.
        Index(
            "uq_payment_requisites_account_card_non_archived",
            "account_id",
            "card_number",
            unique=True,
            postgresql_where=text("NOT is_archived"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    type: Mapped[PaymentRequisiteType] = mapped_column(
        SAEnum(
            PaymentRequisiteType,
            values_callable=lambda enum: [member.value for member in enum],
            name="payment_requisite_type",
        ),
        nullable=False,
    )
    bank_name: Mapped[str] = mapped_column(String(255), nullable=False)
    holder_name: Mapped[str] = mapped_column(String(255), nullable=False)
    card_number: Mapped[str] = mapped_column(String(32), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
