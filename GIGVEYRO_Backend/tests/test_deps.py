import uuid

import pytest
from fastapi import HTTPException

from app.api.deps import require_roles
from app.enums.account import UserRole
from app.models.account import Account


def _account(role: UserRole) -> Account:
    return Account(
        id=uuid.uuid4(),
        username="test-account",
        password_hash="hashed",
        role=role,
        full_name="Test Account",
        is_active=True,
    )


async def test_require_roles_accepts_matching_role():
    dependency = require_roles(UserRole.OWNER)
    owner = _account(UserRole.OWNER)

    result = await dependency(account=owner)

    assert result is owner


async def test_require_roles_rejects_non_matching_role():
    dependency = require_roles(UserRole.OWNER)
    user = _account(UserRole.USER)

    with pytest.raises(HTTPException) as exc_info:
        await dependency(account=user)

    assert exc_info.value.status_code == 403
