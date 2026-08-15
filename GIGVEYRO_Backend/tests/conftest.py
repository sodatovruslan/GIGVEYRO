import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import engine


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
