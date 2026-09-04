"""Seed deterministic, test-only personas in the disposable Playwright database."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.security import hash_password
from app.core.totp_crypto import encrypt_totp_secret
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.enums.deposit import (
    CorrelationStatus,
    DepositAsset,
    DepositNetwork,
    DepositStatus,
    ReconciliationStatus,
)
from app.enums.notification import NotificationMessageKey, NotificationType
from app.enums.payment_requisite import PaymentRequisiteType
from app.enums.wallet import Currency
from app.models.account import Account
from app.models.deposit import Deposit, UnmatchedTransfer
from app.models.merchant_wallet import MerchantWallet
from app.models.notification import Notification, NotificationPreference
from app.models.payment_requisite import PaymentRequisite
from app.models.traffic import UserTrafficSettings
from app.models.two_factor import AccountTwoFactor
from app.models.wallet import UserWallet

PERSONAS = (
    ("00000000-0000-4000-8000-000000000001", "e2e_owner", UserRole.OWNER, True),
    ("00000000-0000-4000-8000-000000000002", "e2e_user_a", UserRole.USER, True),
    ("00000000-0000-4000-8000-000000000003", "e2e_user_b", UserRole.USER, True),
    ("00000000-0000-4000-8000-000000000004", "e2e_merchant_a", UserRole.MERCHANT, True),
    ("00000000-0000-4000-8000-000000000005", "e2e_merchant_b", UserRole.MERCHANT, True),
    ("00000000-0000-4000-8000-000000000006", "e2e_blocked", UserRole.USER, False),
)


async def seed() -> None:
    password = os.environ["E2E_PERSONA_PASSWORD"]
    totp_secret = os.environ["E2E_OWNER_TOTP_SECRET"]
    async with AsyncSessionLocal() as session:
        accounts: dict[str, Account] = {}
        for raw_id, username, role, active in PERSONAS:
            account = Account(
                id=uuid.UUID(raw_id),
                username=username,
                password_hash=hash_password(password),
                role=role,
                full_name=username.replace("_", " ").title(),
                email=f"{username}@e2e.invalid",
                is_active=active,
            )
            session.add(account)
            accounts[username] = account
        await session.flush()

        session.add(
            AccountTwoFactor(
                account_id=accounts["e2e_owner"].id,
                method="totp",
                encrypted_secret=encrypt_totp_secret(totp_secret),
            )
        )

        for username in ("e2e_user_a", "e2e_user_b", "e2e_blocked"):
            account = accounts[username]
            session.add_all(
                [
                    UserWallet(
                        account_id=account.id,
                        currency=Currency.USDT,
                        available_balance=Decimal("25")
                        if username == "e2e_user_a"
                        else Decimal("7"),
                    ),
                    UserTrafficSettings(account_id=account.id, is_enabled=account.is_active),
                    NotificationPreference(account_id=account.id),
                ]
            )

        for username in ("e2e_merchant_a", "e2e_merchant_b"):
            account = accounts[username]
            session.add_all(
                [
                    MerchantWallet(
                        account_id=account.id,
                        currency=Currency.USDT,
                        available_balance=Decimal("100")
                        if username == "e2e_merchant_a"
                        else Decimal("13"),
                    ),
                    NotificationPreference(account_id=account.id),
                ]
            )

        session.add(
            PaymentRequisite(
                account_id=accounts["e2e_user_a"].id,
                type=PaymentRequisiteType.BANK_CARD,
                bank_name="E2E Bank",
                holder_name="E2E User A",
                card_number="4111111111111234",
                phone_number="+992900000001",
                is_active=True,
            )
        )
        session.add_all(
            [
                Notification(
                    account_id=accounts["e2e_user_a"].id,
                    type=NotificationType.SECURITY_EVENT,
                    title="Security event",
                    message="Security settings changed.",
                    message_key=NotificationMessageKey.SECURITY_PASSWORD_CHANGED.value,
                    message_params={},
                    payload={"url": "/user/settings"},
                ),
                Notification(
                    account_id=accounts["e2e_user_b"].id,
                    type=NotificationType.SECURITY_EVENT,
                    title="USER B PRIVATE MARKER",
                    message="USER B PRIVATE MARKER",
                    message_key=NotificationMessageKey.SECURITY_SESSION_REVOKED.value,
                    message_params={},
                    payload={"url": "/user/settings"},
                ),
                Notification(
                    account_id=accounts["e2e_merchant_b"].id,
                    type=NotificationType.SECURITY_EVENT,
                    title="MERCHANT B PRIVATE MARKER",
                    message="MERCHANT B PRIVATE MARKER",
                    message_key=NotificationMessageKey.SECURITY_SESSION_REVOKED.value,
                    message_params={},
                    payload={"url": "/merchant/settings"},
                ),
            ]
        )
        now = datetime.now(UTC)
        session.add_all(
            [
                Deposit(
                    id=uuid.UUID("00000000-0000-4000-8000-000000000101"),
                    public_id="DEP-E2E-LINK",
                    account_id=accounts["e2e_user_a"].id,
                    network=DepositNetwork.TRC20,
                    asset=DepositAsset.USDT,
                    expected_amount=Decimal("12"),
                    deposit_address="TMOCK_GIGVEYRO_DEPOSIT_ADDRESS",
                    confirmations=0,
                    required_confirmations=20,
                    status=DepositStatus.WAITING,
                    expires_at=now + timedelta(hours=1),
                ),
                UnmatchedTransfer(
                    id=uuid.UUID("00000000-0000-4000-8000-000000000201"),
                    tx_hash="tx-e2e-link",
                    provider_event_id="e2e:tx-link:0",
                    from_address="TE2ESENDERADDRESS000001",
                    to_address="TMOCK_GIGVEYRO_DEPOSIT_ADDRESS",
                    amount=Decimal("12"),
                    asset_contract="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
                    provider="e2e",
                    network=DepositNetwork.TRC20,
                    confirmations=20,
                    is_finalized=True,
                    block_number=1001,
                    block_timestamp=now,
                    correlation_status=CorrelationStatus.UNMATCHED,
                    reconciliation_status=ReconciliationStatus.PENDING,
                    reason="E2E_EXACT_CANDIDATE",
                ),
                UnmatchedTransfer(
                    id=uuid.UUID("00000000-0000-4000-8000-000000000202"),
                    tx_hash="tx-e2e-ignore",
                    provider_event_id="e2e:tx-ignore:0",
                    from_address="TE2ESENDERADDRESS000002",
                    to_address="TMOCK_GIGVEYRO_DEPOSIT_ADDRESS",
                    amount=Decimal("88"),
                    asset_contract="TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
                    provider="e2e",
                    network=DepositNetwork.TRC20,
                    confirmations=20,
                    is_finalized=True,
                    block_number=1002,
                    block_timestamp=now,
                    correlation_status=CorrelationStatus.UNMATCHED,
                    reconciliation_status=ReconciliationStatus.PENDING,
                    reason="E2E_NO_MATCH",
                ),
            ]
        )
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
