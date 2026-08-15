import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.session import engine, get_db
from app.enums.account import UserRole
from app.main import app
from app.models.account import Account


@pytest.fixture
async def db_session():
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as async_client:
            yield async_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def make_account(db_session):
    async def _make(
        *,
        role: UserRole = UserRole.USER,
        password: str = "DefaultPassword123",
        is_active: bool = True,
        username: str | None = None,
        full_name: str = "Test Account",
        email: str | None = None,
        phone: str | None = None,
    ) -> Account:
        account = Account(
            username=username or f"acct_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password(password),
            role=role,
            full_name=full_name,
            email=email,
            phone=phone,
            is_active=is_active,
        )
        db_session.add(account)
        await db_session.flush()
        await db_session.refresh(account)
        return account

    return _make
