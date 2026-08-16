import asyncio
from datetime import UTC, datetime
from decimal import Decimal
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.enums.account import UserRole
from app.enums.deposit import CorrelationStatus, DepositAsset, DepositNetwork, DepositStatus
from app.main import app
from app.models.deposit import UnmatchedTransfer
from app.repositories.deposit import DepositRepository
from app.services.deposit import DepositService
from app.services.deposit_provider import MockTRC20DepositProvider, OnChainTransactionDTO
from app.services.exchange_rate import (
    ConfiguredExchangeRateProvider,
    ExternalExchangeRateProvider,
    FallbackExchangeRateProvider,
)
from app.services.provider_factory import get_deposit_provider, get_exchange_rate_provider, get_payout_provider
from app.services.withdrawal import ExternalPayoutAdapter, MockPayoutProvider, PayoutDisabledError, WithdrawalService


@pytest.mark.asyncio
async def test_stage15_provider_factories():
    deposit_provider = get_deposit_provider()
    assert isinstance(deposit_provider, MockTRC20DepositProvider)

    rate_provider = get_exchange_rate_provider()
    assert isinstance(rate_provider, FallbackExchangeRateProvider)

    payout_provider = get_payout_provider()
    assert isinstance(payout_provider, MockPayoutProvider)


@pytest.mark.asyncio
async def test_ambiguous_deposit_matching_no_automatic_credit(db_session, make_account, make_wallet):
    user1 = await make_account(role=UserRole.USER, username="user_amb_1")
    user2 = await make_account(role=UserRole.USER, username="user_amb_2")
    await make_wallet(user1, available=Decimal("0.00"))
    await make_wallet(user2, available=Decimal("0.00"))

    mock_provider = MockTRC20DepositProvider()
    repo = DepositRepository(db_session)
    deposit_service = DepositService(
        deposit_repository=repo,
        account_repository=None,
        wallet_service=None,
        provider=mock_provider,
    )

    dep1 = await deposit_service.create_deposit_intent(user1, amount=Decimal("100.00"))
    dep2 = await deposit_service.create_deposit_intent(user2, amount=Decimal("100.00"))

    tx = OnChainTransactionDTO(
        tx_hash="0xAMBIGUOUS_TX_HASH_123",
        network=DepositNetwork.TRC20,
        asset_contract=settings.USDT_TRC20_CONTRACT_ADDRESS,
        from_address="TFROM_ADDRESS",
        to_address=settings.USDT_TRC20_DEPOSIT_ADDRESS,
        amount=Decimal("100.00"),
        confirmations=25,
        is_success=True,
        timestamp=datetime.now(UTC),
    )
    mock_provider.add_simulated_tx(tx)

    processed = await deposit_service.scan_and_correlate_deposits()
    assert processed == 0

    unmatched = await repo.get_unmatched_by_tx_hash("0xAMBIGUOUS_TX_HASH_123")
    assert unmatched is not None
    assert unmatched.correlation_status == CorrelationStatus.AMBIGUOUS

    dep1_refreshed = await repo.get_by_id(dep1.id)
    dep2_refreshed = await repo.get_by_id(dep2.id)
    assert dep1_refreshed.status == DepositStatus.WAITING
    assert dep2_refreshed.status == DepositStatus.WAITING


@pytest.mark.asyncio
async def test_unmatched_transfer_saved(db_session):
    mock_provider = MockTRC20DepositProvider()
    repo = DepositRepository(db_session)
    deposit_service = DepositService(
        deposit_repository=repo,
        account_repository=None,
        wallet_service=None,
        provider=mock_provider,
    )

    tx = OnChainTransactionDTO(
        tx_hash="0xUNMATCHED_TX_HASH_999",
        network=DepositNetwork.TRC20,
        asset_contract=settings.USDT_TRC20_CONTRACT_ADDRESS,
        from_address="TFROM_ADDRESS",
        to_address=settings.USDT_TRC20_DEPOSIT_ADDRESS,
        amount=Decimal("555.00"),
        confirmations=25,
        is_success=True,
        timestamp=datetime.now(UTC),
    )
    mock_provider.add_simulated_tx(tx)

    await deposit_service.scan_and_correlate_deposits()

    unmatched = await repo.get_unmatched_by_tx_hash("0xUNMATCHED_TX_HASH_999")
    assert unmatched is not None
    assert unmatched.correlation_status == CorrelationStatus.UNMATCHED


@pytest.mark.asyncio
async def test_payout_safety_disabled_by_default():
    adapter = ExternalPayoutAdapter()
    with pytest.raises(PayoutDisabledError):
        await adapter.request_payout(uuid.uuid4(), Decimal("100.00"), "TDESTINATION_ADDRESS")


@pytest.mark.asyncio
async def test_owner_integrations_diagnostics_auth(make_account):
    owner = await make_account(role=UserRole.OWNER, username="diag_owner")
    user = await make_account(role=UserRole.USER, username="diag_user")

    from app.core.security import create_access_token
    owner_token = create_access_token(subject=owner.id, role=owner.role.value)
    user_token = create_access_token(subject=user.id, role=user.role.value)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/owner/integrations/diagnostics")
        assert res.status_code == 401

        res_user = await client.get(
            "/api/v1/owner/integrations/diagnostics",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert res_user.status_code == 403

        res_owner = await client.get(
            "/api/v1/owner/integrations/diagnostics",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert res_owner.status_code == 200
        data = res_owner.json()
        assert data["status"] == "healthy"
        assert "payout_enabled" in data["safety"]
