import asyncio

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.models.account import Account

NEW_PASSWORD = "OwnerTest12345"


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Account).where(Account.role == UserRole.OWNER)
        )
        owner = result.scalar_one_or_none()

        if owner is None:
            print("OWNER not found")
            return

        owner.password_hash = hash_password(NEW_PASSWORD)
        await session.commit()

        print("OWNER password reset successfully")
        print("Username:", owner.username)


if __name__ == "__main__":
    asyncio.run(main())