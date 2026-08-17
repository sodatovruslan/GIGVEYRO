"""Bootstrap the first OWNER account.

Run with: python -m app.scripts.create_owner

There is intentionally no public HTTP endpoint for this - creating an OWNER
is a one-time, operator-only action.
"""

import asyncio
import getpass
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.models import Account
from app.repositories.account import AccountRepository


class OwnerBootstrapError(Exception):
    """Raised when the OWNER bootstrap cannot proceed safely."""


async def bootstrap_owner(
    session: AsyncSession,
    *,
    username: str,
    full_name: str,
    password: str,
    email: str | None = None,
    phone: str | None = None,
) -> Account:
    if not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
        raise OwnerBootstrapError(
            f"password must be between {MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH} characters"
        )

    repository = AccountRepository(session)

    if await repository.get_by_role(UserRole.OWNER) is not None:
        raise OwnerBootstrapError("an OWNER account already exists")

    if await repository.exists_by_username(username):
        raise OwnerBootstrapError(f"username '{username}' is already taken")

    if email is not None and await repository.get_by_email(email) is not None:
        raise OwnerBootstrapError(f"email '{email}' is already in use")

    if phone is not None and await repository.get_by_phone(phone) is not None:
        raise OwnerBootstrapError(f"phone '{phone}' is already in use")

    owner = Account(
        username=username,
        password_hash=hash_password(password),
        role=UserRole.OWNER,
        full_name=full_name,
        email=email,
        phone=phone,
        is_active=True,
    )
    return await repository.create(owner)


def _prompt_required(label: str) -> str:
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print(f"{label} cannot be empty.")


def _prompt_optional(label: str) -> str | None:
    value = input(f"{label} (optional, press Enter to skip): ").strip()
    return value or None


def _prompt_password() -> str:
    while True:
        password = getpass.getpass("Password: ")
        if not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
            print(f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters.")
            continue
        if getpass.getpass("Confirm password: ") != password:
            print("Passwords do not match.")
            continue
        return password


async def _run_interactive() -> None:
    async with AsyncSessionLocal() as session:
        repository = AccountRepository(session)
        if await repository.get_by_role(UserRole.OWNER) is not None:
            print("An OWNER account already exists. Refusing to create a second one.")
            return

        username = _prompt_required("Username")
        full_name = _prompt_required("Full name")
        email = _prompt_optional("Email")
        phone = _prompt_optional("Phone")
        password = _prompt_password()

        try:
            owner = await bootstrap_owner(
                session,
                username=username,
                full_name=full_name,
                password=password,
                email=email,
                phone=phone,
            )
        except OwnerBootstrapError as exc:
            print(f"Cannot create OWNER: {exc}")
            return

        await session.commit()

    print(f"OWNER account '{owner.username}' created successfully.")


def main() -> None:
    try:
        asyncio.run(_run_interactive())
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
