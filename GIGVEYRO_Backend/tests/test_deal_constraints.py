from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.models.deal import Deal
from app.services.deal import generate_public_id


async def test_negative_amount_tjs_rejected_by_db(make_account, db_session):
    merchant = await make_account(role=UserRole.MERCHANT)

    async with db_session.begin_nested():
        deal = Deal(
            public_id=generate_public_id(),
            merchant_id=merchant.id,
            amount_tjs=Decimal("-10"),
            status=DealStatus.CREATED,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        db_session.add(deal)
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_zero_amount_tjs_rejected_by_db(make_account, db_session):
    merchant = await make_account(role=UserRole.MERCHANT)

    async with db_session.begin_nested():
        deal = Deal(
            public_id=generate_public_id(),
            merchant_id=merchant.id,
            amount_tjs=Decimal("0"),
            status=DealStatus.CREATED,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        db_session.add(deal)
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_negative_amount_usdt_rejected_by_db(make_account, db_session):
    merchant = await make_account(role=UserRole.MERCHANT)

    async with db_session.begin_nested():
        deal = Deal(
            public_id=generate_public_id(),
            merchant_id=merchant.id,
            amount_tjs=Decimal("100"),
            amount_usdt=Decimal("-1"),
            status=DealStatus.CREATED,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        db_session.add(deal)
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_negative_exchange_rate_rejected_by_db(make_account, db_session):
    merchant = await make_account(role=UserRole.MERCHANT)

    async with db_session.begin_nested():
        deal = Deal(
            public_id=generate_public_id(),
            merchant_id=merchant.id,
            amount_tjs=Decimal("100"),
            exchange_rate=Decimal("-1"),
            status=DealStatus.CREATED,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        db_session.add(deal)
        with pytest.raises(IntegrityError):
            await db_session.flush()


async def test_null_amount_usdt_and_exchange_rate_allowed(make_account, db_session):
    merchant = await make_account(role=UserRole.MERCHANT)

    deal = Deal(
        public_id=generate_public_id(),
        merchant_id=merchant.id,
        amount_tjs=Decimal("100"),
        status=DealStatus.CREATED,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db_session.add(deal)
    await db_session.flush()

    assert deal.amount_usdt is None
    assert deal.exchange_rate is None


async def test_public_id_unique(make_account, db_session):
    merchant = await make_account(role=UserRole.MERCHANT)
    public_id = generate_public_id()

    deal = Deal(
        public_id=public_id,
        merchant_id=merchant.id,
        amount_tjs=Decimal("100"),
        status=DealStatus.CREATED,
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db_session.add(deal)
    await db_session.flush()

    async with db_session.begin_nested():
        duplicate = Deal(
            public_id=public_id,
            merchant_id=merchant.id,
            amount_tjs=Decimal("50"),
            status=DealStatus.CREATED,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        db_session.add(duplicate)
        with pytest.raises(IntegrityError):
            await db_session.flush()
