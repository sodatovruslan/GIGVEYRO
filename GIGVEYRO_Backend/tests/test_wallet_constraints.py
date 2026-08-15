from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.enums.account import UserRole
from app.enums.wallet import Currency
from app.models.wallet import UserWallet


async def test_negative_available_balance_rejected_by_db(make_account, make_wallet, db_session):
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user)

    async with db_session.begin_nested():
        wallet.available_balance = Decimal("-1")
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_negative_insurance_balance_rejected_by_db(make_account, db_session):
    user = await make_account(role=UserRole.USER)

    async with db_session.begin_nested():
        wallet = UserWallet(
            account_id=user.id,
            currency=Currency.USDT,
            available_balance=Decimal("0"),
            insurance_balance=Decimal("-1"),
            frozen_balance=Decimal("0"),
        )
        db_session.add(wallet)
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_negative_frozen_balance_rejected_by_db(make_account, db_session):
    user = await make_account(role=UserRole.USER)

    async with db_session.begin_nested():
        wallet = UserWallet(
            account_id=user.id,
            currency=Currency.USDT,
            available_balance=Decimal("0"),
            insurance_balance=Decimal("0"),
            frozen_balance=Decimal("-1"),
        )
        db_session.add(wallet)
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_one_wallet_per_account_enforced_by_db(make_account, make_wallet, db_session):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)

    async with db_session.begin_nested():
        duplicate = UserWallet(account_id=user.id, currency=Currency.USDT)
        db_session.add(duplicate)
        with pytest.raises(IntegrityError):
            await db_session.flush()
