import uuid
from datetime import UTC, datetime

from app.enums.account import UserRole
from app.models.account import Account
from app.repositories.account import AccountRepository
from app.schemas.account import AccountRead


def test_user_role_values():
    assert {role.value for role in UserRole} == {"owner", "user", "merchant", "team_lead"}
    assert UserRole.OWNER == "owner"
    assert UserRole.USER == "user"
    assert UserRole.MERCHANT == "merchant"
    assert UserRole.TEAM_LEAD == "team_lead"


def test_account_read_excludes_password_hash():
    assert "password_hash" not in AccountRead.model_fields


def test_account_read_serializes_from_account_object():
    account = Account(
        id=uuid.uuid4(),
        username="owner1",
        password_hash="hashed",
        role=UserRole.OWNER,
        full_name="Owner One",
        email="owner@example.com",
        phone=None,
        is_active=True,
        is_verified=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    schema = AccountRead.model_validate(account)

    assert schema.username == "owner1"
    assert schema.role == UserRole.OWNER
    assert not hasattr(schema, "password_hash")


async def test_repository_get_by_username(db_session):
    repository = AccountRepository(db_session)
    username = f"test_user_{uuid.uuid4().hex[:8]}"
    account = Account(
        username=username,
        password_hash="hashed",
        role=UserRole.USER,
        full_name="Test User",
    )
    db_session.add(account)
    await db_session.flush()

    found = await repository.get_by_username(username)

    assert found is not None
    assert found.username == username
    assert found.role == UserRole.USER


async def test_repository_get_by_id(db_session):
    repository = AccountRepository(db_session)
    username = f"test_user_{uuid.uuid4().hex[:8]}"
    account = Account(
        username=username,
        password_hash="hashed",
        role=UserRole.MERCHANT,
        full_name="Test Merchant",
    )
    db_session.add(account)
    await db_session.flush()
    await db_session.refresh(account)

    found = await repository.get_by_id(account.id)

    assert found is not None
    assert found.id == account.id
    assert found.role == UserRole.MERCHANT


async def test_repository_get_by_username_not_found(db_session):
    repository = AccountRepository(db_session)
    found = await repository.get_by_username("definitely-not-existing-user")
    assert found is None
