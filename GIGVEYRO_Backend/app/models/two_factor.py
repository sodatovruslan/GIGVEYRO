import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AccountTwoFactor(Base):
    """Confirmed, active 2FA configuration for an account.

    Only exists once setup has been confirmed - see PendingTwoFactorSetup
    for the not-yet-confirmed state. encrypted_secret is ciphertext only
    (see app.core.totp_crypto), never the plaintext TOTP secret.
    """

    __tablename__ = "account_two_factor"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="totp")
    encrypted_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PendingTwoFactorSetup(Base):
    """A generated-but-not-yet-confirmed TOTP secret.

    Short-lived (TWO_FACTOR_SETUP_EXPIRE_MINUTES); starting a new setup
    replaces any existing pending row for the account rather than
    accumulating abandoned attempts.
    """

    __tablename__ = "two_factor_pending_setups"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    encrypted_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TwoFactorRecoveryCode(Base):
    """One single-use recovery code. Only the hash is stored."""

    __tablename__ = "two_factor_recovery_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TwoFactorChallenge(Base):
    """Server-side record backing a two_factor_challenge JWT (jti == id).

    Tracked so a challenge can be consumed exactly once and brute-force
    attempts against a single challenge are bounded, independent of the
    IP-based rate limiter on the verify endpoint.
    """

    __tablename__ = "two_factor_challenges"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
