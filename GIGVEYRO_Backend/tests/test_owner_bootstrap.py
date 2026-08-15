import uuid

import pytest
from sqlalchemy import delete

from app.enums.account import UserRole
from app.models.account import Account
from app.scripts.create_owner import OwnerBootstrapError, bootstrap_owner


async def _clear_owners(db_session) -> None:
    # The dev DB may already have a real bootstrapped OWNER (e.g. from a
    # manual E2E run). Removing it here only affects this test's rolled-back
    # transaction, not the persisted row.
    await db_session.execute(delete(Account).where(Account.role == UserRole.OWNER))
    await db_session.flush()


async def test_bootstrap_owner_creates_account(db_session):
    await _clear_owners(db_session)

    owner = await bootstrap_owner(
        db_session,
        username=f"owner_{uuid.uuid4().hex[:8]}",
        full_name="Test Owner",
        password="StrongPassword123",
    )

    assert owner.role == UserRole.OWNER
    assert owner.is_active is True
    assert owner.password_hash != "StrongPassword123"


async def test_bootstrap_owner_rejects_duplicate_owner(db_session):
    await _clear_owners(db_session)

    await bootstrap_owner(
        db_session,
        username=f"owner_{uuid.uuid4().hex[:8]}",
        full_name="First Owner",
        password="StrongPassword123",
    )

    with pytest.raises(OwnerBootstrapError, match="already exists"):
        await bootstrap_owner(
            db_session,
            username=f"owner_{uuid.uuid4().hex[:8]}",
            full_name="Second Owner",
            password="StrongPassword123",
        )


async def test_bootstrap_owner_rejects_duplicate_username(db_session):
    await _clear_owners(db_session)

    username = f"existing_{uuid.uuid4().hex[:8]}"
    db_session.add(
        Account(
            username=username,
            password_hash="hashed",
            role=UserRole.USER,
            full_name="Existing User",
        )
    )
    await db_session.flush()

    with pytest.raises(OwnerBootstrapError, match="already taken"):
        await bootstrap_owner(
            db_session,
            username=username,
            full_name="New Owner",
            password="StrongPassword123",
        )


async def test_bootstrap_owner_rejects_short_password(db_session):
    with pytest.raises(OwnerBootstrapError):
        await bootstrap_owner(
            db_session,
            username=f"owner_{uuid.uuid4().hex[:8]}",
            full_name="Test Owner",
            password="short",
        )
