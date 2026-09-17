import asyncio
import os
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest
from dotenv import dotenv_values
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

# Test settings and the disposable database URL must be established before app
# modules instantiate their process-wide settings, engine, and ASGI application.
# ruff: noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_VALUES = dotenv_values(_PROJECT_ROOT / ".env")
_BASE_DATABASE_URL = os.environ.get("DATABASE_URL") or _ENV_VALUES.get("DATABASE_URL")
if not _BASE_DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required to derive the isolated pytest database")

_base_url = make_url(str(_BASE_DATABASE_URL))
_base_database = _base_url.database or "gigveyro"
_TEST_DATABASE_NAME = f"{_base_database[:42]}_pytest_{os.getpid()}"
if not re.fullmatch(r"[A-Za-z0-9_]+", _TEST_DATABASE_NAME):
    raise RuntimeError("Derived pytest database name contains unsafe characters")

_TEST_DATABASE_URL = _base_url.set(database=_TEST_DATABASE_NAME)
_ADMIN_DATABASE_URL = _base_url.set(drivername="postgresql", database="postgres")
os.environ["APP_ENV"] = "test"
os.environ["DEBUG"] = "false"
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL.render_as_string(hide_password=False)
# Standard tests must never inherit a developer's live Telegram configuration.
os.environ["TELEGRAM_BOT_ENABLED"] = "false"
os.environ["TELEGRAM_DELIVERY_ENABLED"] = "false"

from app.core.config import settings as app_settings
from app.core.middleware import in_memory_rate_limiter
from app.core.security import hash_password, hash_refresh_token
from app.db.session import engine, get_db
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.enums.deposit import DepositAsset, DepositNetwork, DepositStatus
from app.enums.payment_requisite import PaymentRequisiteType
from app.enums.wallet import Currency
from app.main import app
from app.models.account import Account
from app.models.auth_session import AuthSession
from app.models.deal import Deal
from app.models.deposit import Deposit
from app.models.merchant_wallet import MerchantWallet
from app.models.payment_requisite import PaymentRequisite
from app.models.traffic import UserTrafficSettings
from app.models.wallet import UserWallet
from app.services.deal import generate_public_id
from app.services.deposit import generate_deposit_public_id
from app.services.login_protection import in_memory_account_login_guard


async def _create_test_database() -> None:
    connection = await asyncpg.connect(_ADMIN_DATABASE_URL.render_as_string(hide_password=False))
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", _TEST_DATABASE_NAME
        )
        if exists:
            raise RuntimeError(f"Refusing to replace existing test database {_TEST_DATABASE_NAME}")
        await connection.execute(f'CREATE DATABASE "{_TEST_DATABASE_NAME}"')
    finally:
        await connection.close()


async def _drop_test_database() -> None:
    connection = await asyncpg.connect(_ADMIN_DATABASE_URL.render_as_string(hide_password=False))
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{_TEST_DATABASE_NAME}" WITH (FORCE)')
    finally:
        await connection.close()


def pytest_sessionstart(session: pytest.Session) -> None:
    asyncio.run(_create_test_database())
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_PROJECT_ROOT,
        env=os.environ.copy(),
        check=True,
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    asyncio.run(_drop_test_database())


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    in_memory_rate_limiter._hits.clear()
    in_memory_account_login_guard._state.clear()
    yield
    in_memory_rate_limiter._hits.clear()
    in_memory_account_login_guard._state.clear()


# Test-only DNS map for app.core.url_safety - keeps webhook SSRF-safety
# tests offline/deterministic instead of depending on real DNS resolution.
# A literal IP address as "hostname" resolves to itself (matching real
# getaddrinfo behavior for numeric hosts), covering every private/loopback/
# link-local/etc test case without needing an entry here. Named entries
# cover the "a hostname resolves to a private address" cases that a plain
# IP literal can't exercise.
_TEST_DNS_MAP: dict[str, list[str]] = {
    "example.com": ["93.184.216.34"],
    "public-webhook.test": ["1.1.1.1"],
    "also-public-webhook.test": ["8.8.8.8"],
    "internal-service.test": ["10.0.0.5"],
    "metadata.test": ["169.254.169.254"],
    "mixed-address.test": ["8.8.4.4", "10.0.0.9"],
    "rebind.test": ["1.0.0.1"],
}


@pytest.fixture(autouse=True)
def fake_dns_for_webhook_safety(monkeypatch):
    import socket as socket_module

    from app.core import url_safety

    async def _fake_getaddrinfo(hostname: str, port: int):
        try:
            import ipaddress

            ipaddress.ip_address(hostname.split("%", 1)[0])
            ips = [hostname]
        except ValueError:
            ips = _TEST_DNS_MAP.get(hostname)
            if ips is None:
                raise socket_module.gaierror(f"no test DNS entry for host: {hostname}")
        return [
            (socket_module.AF_INET, socket_module.SOCK_STREAM, 6, "", (ip, port)) for ip in ips
        ]

    monkeypatch.setattr(url_safety, "_getaddrinfo", _fake_getaddrinfo)


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
        insurance_target: Decimal = Decimal("0"),
    ) -> UserWallet:
        wallet = UserWallet(
            account_id=account.id,
            currency=Currency.USDT,
            available_balance=available,
            insurance_balance=insurance,
            frozen_balance=frozen,
            insurance_target=insurance_target,
        )
        db_session.add(wallet)
        await db_session.flush()
        await db_session.refresh(wallet)
        return wallet

    return _make


@pytest.fixture
def make_merchant_wallet(db_session):
    async def _make(
        account: Account,
        *,
        available: Decimal = Decimal("0"),
    ) -> MerchantWallet:
        wallet = MerchantWallet(
            account_id=account.id,
            currency=Currency.USDT,
            available_balance=available,
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
def make_auth_session(db_session):
    async def _make(
        account: Account,
        *,
        refresh_token: str | None = None,
        expires_in_days: int = 30,
        revoked_at: datetime | None = None,
        revoked_reason: str | None = None,
    ) -> AuthSession:
        token = refresh_token or uuid.uuid4().hex
        session = AuthSession(
            account_id=account.id,
            refresh_token_hash=hash_refresh_token(token),
            expires_at=datetime.now(UTC) + timedelta(days=expires_in_days),
            revoked_at=revoked_at,
            revoked_reason=revoked_reason,
        )
        db_session.add(session)
        await db_session.flush()
        await db_session.refresh(session)
        return session

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
        amount_usdt: Decimal | None = None,
    ) -> Deal:
        deal = Deal(
            public_id=generate_public_id(),
            merchant_id=merchant.id,
            user_id=user.id if user else None,
            amount_tjs=amount_tjs,
            amount_usdt=amount_usdt,
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
