import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.security import hash_password
from app.db.session import engine, get_db
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.enums.deposit import DepositAsset, DepositNetwork, DepositStatus
from app.enums.payment_requisite import PaymentRequisiteType
from app.enums.wallet import Currency
from app.main import app
from app.models.account import Account
from app.models.deal import Deal
from app.models.deposit import Deposit
from app.models.payment_requisite import PaymentRequisite
from app.models.traffic import UserTrafficSettings
from app.models.wallet import UserWallet
from app.services.deal import generate_public_id
from app.services.deposit import generate_deposit_public_id


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


@pytest.fixture
def make_wallet(db_session):
    async def _make(
        account: Account,
        *,
        available: Decimal = Decimal("0"),
        insurance: Decimal = Decimal("0"),
        frozen: Decimal = Decimal("0"),
    ) -> UserWallet:
        wallet = UserWallet(
            account_id=account.id,
            currency=Currency.USDT,
            available_balance=available,
            insurance_balance=insurance,
            frozen_balance=frozen,
        )
        db_session.add(wallet)
        await db_session.flush()
        await db_session.refresh(wallet)
        return wallet

    return _make


@pytest.fixture
def make_requisite(db_session):
    async def _make(
        account: Account,
        *,
        card_number: str = "4111111111111234",
        bank_name: str = "Test Bank",
        holder_name: str = "Test Holder",
        phone_number: str | None = None,
        is_active: bool = True,
        is_archived: bool = False,
    ) -> PaymentRequisite:
        requisite = PaymentRequisite(
            account_id=account.id,
            type=PaymentRequisiteType.BANK_CARD,
            bank_name=bank_name,
            holder_name=holder_name,
            card_number=card_number,
            phone_number=phone_number,
            is_active=is_active,
            is_archived=is_archived,
        )
        db_session.add(requisite)
        await db_session.flush()
        await db_session.refresh(requisite)
        return requisite

    return _make


@pytest.fixture
def make_traffic_settings(db_session):
    async def _make(account: Account, *, is_enabled: bool = False) -> UserTrafficSettings:
        settings = UserTrafficSettings(account_id=account.id, is_enabled=is_enabled)
        db_session.add(settings)
        await db_session.flush()
        await db_session.refresh(settings)
        return settings

    return _make


@pytest.fixture
def make_deal(db_session):
    async def _make(
        merchant: Account,
        *,
        amount_tjs: Decimal = Decimal("200"),
        status: DealStatus = DealStatus.AVAILABLE,
        expires_in_minutes: int = 30,
        user: Account | None = None,
    ) -> Deal:
        deal = Deal(
            public_id=generate_public_id(),
            merchant_id=merchant.id,
            user_id=user.id if user else None,
            amount_tjs=amount_tjs,
            status=status,
            expires_at=datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
        )
        db_session.add(deal)
        await db_session.flush()
        await db_session.refresh(deal)
        return deal

    return _make


@pytest.fixture
def make_deposit(db_session):
    async def _make(
        account: Account,
        *,
        expected_amount: Decimal = Decimal("100"),
        status: DepositStatus = DepositStatus.WAITING,
        expires_in_minutes: int = 30,
        required_confirmations: int = 20,
        tx_hash: str | None = None,
        received_amount: Decimal | None = None,
        confirmations: int = 0,
    ) -> Deposit:
        deposit = Deposit(
            public_id=generate_deposit_public_id(),
            account_id=account.id,
            network=DepositNetwork.TRC20,
            asset=DepositAsset.USDT,
            expected_amount=expected_amount,
            deposit_address=app_settings.USDT_TRC20_DEPOSIT_ADDRESS,
            tx_hash=tx_hash,
            received_amount=received_amount,
            confirmations=confirmations,
            required_confirmations=required_confirmations,
            status=status,
            expires_at=datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
        )
        db_session.add(deposit)
        await db_session.flush()
        await db_session.refresh(deposit)
        return deposit

    return _make
