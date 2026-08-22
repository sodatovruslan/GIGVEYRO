import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deposit import DepositNetwork
from app.models.deposit import UnmatchedTransfer
from app.repositories.account import AccountRepository
from app.repositories.deposit import DepositRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.wallet import WalletRepository
from app.services.deposit import DepositService
from app.services.deposit_provider import MockTRC20DepositProvider, OnChainTransactionDTO
from app.services.wallet import WalletService


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


def _tx(*, tx_hash: str, amount: Decimal, is_success: bool = True) -> OnChainTransactionDTO:
    return OnChainTransactionDTO(
        tx_hash=tx_hash,
        network=DepositNetwork.TRC20,
        asset_contract=settings.USDT_TRC20_CONTRACT_ADDRESS,
        from_address=f"T-sender-{uuid.uuid4().hex[:8]}",
        to_address=settings.USDT_TRC20_DEPOSIT_ADDRESS,
        amount=amount,
        confirmations=20,
        is_success=is_success,
        timestamp=datetime.now(UTC),
    )


@pytest.fixture
def make_deposit_service(db_session: AsyncSession):
    def _make(provider: MockTRC20DepositProvider) -> DepositService:
        account_repo = AccountRepository(db_session)
        wallet_service = WalletService(
            WalletRepository(db_session), LedgerRepository(db_session), account_repo
        )
        return DepositService(
            DepositRepository(db_session), account_repo, wallet_service, provider
        )

    return _make


async def _create_unmatched(
    make_deposit_service, *, tx_hash: str, amount: Decimal = Decimal("999")
):
    provider = MockTRC20DepositProvider()
    provider.add_simulated_tx(_tx(tx_hash=tx_hash, amount=amount))
    await make_deposit_service(provider).scan_and_correlate_deposits()


async def _create_ambiguous(
    make_account, make_wallet, make_deposit, make_deposit_service, *, tx_hash: str
):
    amount = Decimal("321")
    user_a = await make_account(role=UserRole.USER)
    await make_wallet(user_a)
    await make_deposit(user_a, expected_amount=amount)
    user_b = await make_account(role=UserRole.USER)
    await make_wallet(user_b)
    await make_deposit(user_b, expected_amount=amount)

    provider = MockTRC20DepositProvider()
    provider.add_simulated_tx(_tx(tx_hash=tx_hash, amount=amount))
    await make_deposit_service(provider).scan_and_correlate_deposits()


async def test_owner_lists_unmatched_transfers(client, make_account, make_deposit_service):
    owner = await make_account(role=UserRole.OWNER)
    await _create_unmatched(make_deposit_service, tx_hash="tx-unmatched-owner-1")

    response = await client.get("/owner/deposits/unmatched", headers=_auth_headers(owner))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["tx_hash"] == "tx-unmatched-owner-1"
    assert item["correlation_status"] == "UNMATCHED"
    assert item["reason"]
    assert "amount" in item and "from_address" in item and "to_address" in item


async def test_owner_lists_ambiguous_transfers(
    client, make_account, make_wallet, make_deposit, make_deposit_service
):
    owner = await make_account(role=UserRole.OWNER)
    await _create_ambiguous(
        make_account,
        make_wallet,
        make_deposit,
        make_deposit_service,
        tx_hash="tx-ambiguous-owner-1",
    )

    response = await client.get(
        "/owner/deposits/unmatched", params={"status": "AMBIGUOUS"}, headers=_auth_headers(owner)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["correlation_status"] == "AMBIGUOUS"


async def test_owner_filters_unmatched_by_tx_hash(client, make_account, make_deposit_service):
    owner = await make_account(role=UserRole.OWNER)
    await _create_unmatched(make_deposit_service, tx_hash="tx-alpha-1")
    await _create_unmatched(make_deposit_service, tx_hash="tx-beta-1")

    response = await client.get(
        "/owner/deposits/unmatched", params={"tx_hash": "alpha"}, headers=_auth_headers(owner)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["tx_hash"] == "tx-alpha-1"


async def test_owner_filters_unmatched_by_amount_range(client, make_account, make_deposit_service):
    owner = await make_account(role=UserRole.OWNER)
    await _create_unmatched(make_deposit_service, tx_hash="tx-small-1", amount=Decimal("10"))
    await _create_unmatched(make_deposit_service, tx_hash="tx-large-1", amount=Decimal("500"))

    response = await client.get(
        "/owner/deposits/unmatched",
        params={"min_amount": "100", "max_amount": "1000"},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["tx_hash"] == "tx-large-1"


async def test_owner_gets_unmatched_transfer_by_id(
    client, db_session, make_account, make_deposit_service
):
    owner = await make_account(role=UserRole.OWNER)
    await _create_unmatched(make_deposit_service, tx_hash="tx-detail-1")

    transfer = (
        await db_session.execute(
            select(UnmatchedTransfer).where(UnmatchedTransfer.tx_hash == "tx-detail-1")
        )
    ).scalar_one()

    response = await client.get(
        f"/owner/deposits/unmatched/{transfer.id}", headers=_auth_headers(owner)
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(transfer.id)


async def test_owner_gets_nonexistent_unmatched_transfer_returns_404(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    response = await client.get(
        f"/owner/deposits/unmatched/{uuid.uuid4()}", headers=_auth_headers(owner)
    )
    assert response.status_code == 404


async def test_user_forbidden_from_unmatched_transfers(client, make_account):
    user = await make_account(role=UserRole.USER)
    response = await client.get("/owner/deposits/unmatched", headers=_auth_headers(user))
    assert response.status_code == 403


async def test_merchant_forbidden_from_unmatched_transfers(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)
    response = await client.get("/owner/deposits/unmatched", headers=_auth_headers(merchant))
    assert response.status_code == 403


async def test_unmatched_transfers_require_authentication(client):
    response = await client.get("/owner/deposits/unmatched")
    assert response.status_code == 401


async def test_unmatched_transfers_pagination(client, make_account, make_deposit_service):
    owner = await make_account(role=UserRole.OWNER)
    for i in range(3):
        await _create_unmatched(make_deposit_service, tx_hash=f"tx-page-{i}")

    first_page = await client.get(
        "/owner/deposits/unmatched", params={"limit": 2, "offset": 0}, headers=_auth_headers(owner)
    )
    second_page = await client.get(
        "/owner/deposits/unmatched", params={"limit": 2, "offset": 2}, headers=_auth_headers(owner)
    )
    assert first_page.json()["total"] == 3
    assert len(first_page.json()["items"]) == 2
    assert len(second_page.json()["items"]) == 1


async def test_duplicate_correlation_does_not_duplicate_unmatched_record(
    client, make_account, make_deposit_service
):
    owner = await make_account(role=UserRole.OWNER)
    provider = MockTRC20DepositProvider()
    provider.add_simulated_tx(_tx(tx_hash="tx-replay-unmatched-1", amount=Decimal("777")))
    service = make_deposit_service(provider)

    await service.scan_and_correlate_deposits()
    await service.scan_and_correlate_deposits()

    response = await client.get("/owner/deposits/unmatched", headers=_auth_headers(owner))
    assert response.json()["total"] == 1


async def test_unmatched_deposits_endpoints_are_read_only():
    from app.main import app as fastapi_app

    schema = fastapi_app.openapi()
    for path, methods in schema["paths"].items():
        if path.startswith("/owner/deposits/unmatched"):
            assert "post" not in methods
            assert "patch" not in methods
            assert "put" not in methods
            assert "delete" not in methods
