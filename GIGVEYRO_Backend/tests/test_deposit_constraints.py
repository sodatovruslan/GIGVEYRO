from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import settings as app_settings
from app.enums.account import UserRole
from app.enums.deposit import DepositAsset, DepositNetwork, DepositStatus
from app.models.deposit import Deposit
from app.services.deposit import generate_deposit_public_id


def _base_kwargs(account_id):
    return dict(
        public_id=generate_deposit_public_id(),
        account_id=account_id,
        network=DepositNetwork.TRC20,
        asset=DepositAsset.USDT,
        deposit_address=app_settings.USDT_TRC20_DEPOSIT_ADDRESS,
        required_confirmations=20,
        status=DepositStatus.WAITING,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )


async def test_negative_expected_amount_rejected_by_db(make_account, db_session):
    user = await make_account(role=UserRole.USER)

    async with db_session.begin_nested():
        deposit = Deposit(**_base_kwargs(user.id), expected_amount=Decimal("-10"))
        db_session.add(deposit)
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_zero_expected_amount_rejected_by_db(make_account, db_session):
    user = await make_account(role=UserRole.USER)

    async with db_session.begin_nested():
        deposit = Deposit(**_base_kwargs(user.id), expected_amount=Decimal("0"))
        db_session.add(deposit)
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_negative_received_amount_rejected_by_db(make_account, db_session):
    user = await make_account(role=UserRole.USER)

    async with db_session.begin_nested():
        deposit = Deposit(
            **_base_kwargs(user.id),
            expected_amount=Decimal("100"),
            received_amount=Decimal("-1"),
        )
        db_session.add(deposit)
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_negative_credited_amount_rejected_by_db(make_account, db_session):
    user = await make_account(role=UserRole.USER)

    async with db_session.begin_nested():
        deposit = Deposit(
            **_base_kwargs(user.id),
            expected_amount=Decimal("100"),
            credited_amount=Decimal("-1"),
        )
        db_session.add(deposit)
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_negative_confirmations_rejected_by_db(make_account, db_session):
    user = await make_account(role=UserRole.USER)

    async with db_session.begin_nested():
        deposit = Deposit(**_base_kwargs(user.id), expected_amount=Decimal("100"))
        deposit.confirmations = -1
        db_session.add(deposit)
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_duplicate_tx_hash_rejected_by_db(make_account, db_session):
    user = await make_account(role=UserRole.USER)
    shared_tx_hash = "dup_db_level_tx"

    first = Deposit(**_base_kwargs(user.id), expected_amount=Decimal("100"), tx_hash=shared_tx_hash)
    db_session.add(first)
    await db_session.flush()

    async with db_session.begin_nested():
        second = Deposit(
            **_base_kwargs(user.id), expected_amount=Decimal("50"), tx_hash=shared_tx_hash
        )
        db_session.add(second)
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_multiple_null_tx_hash_allowed(make_account, db_session):
    user = await make_account(role=UserRole.USER)

    first = Deposit(**_base_kwargs(user.id), expected_amount=Decimal("100"))
    second = Deposit(**_base_kwargs(user.id), expected_amount=Decimal("50"))
    db_session.add_all([first, second])

    await db_session.flush()

    assert first.tx_hash is None
    assert second.tx_hash is None


async def test_public_id_unique(make_account, db_session):
    user = await make_account(role=UserRole.USER)
    public_id = generate_deposit_public_id()

    first = Deposit(
        **{**_base_kwargs(user.id), "public_id": public_id}, expected_amount=Decimal("100")
    )
    db_session.add(first)
    await db_session.flush()

    async with db_session.begin_nested():
        second = Deposit(
            **{**_base_kwargs(user.id), "public_id": public_id}, expected_amount=Decimal("50")
        )
        db_session.add(second)
        with pytest.raises(IntegrityError):
            await db_session.flush()
