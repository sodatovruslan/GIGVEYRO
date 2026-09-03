import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.enums.account import UserRole
from app.enums.deposit import CorrelationStatus, DepositNetwork, DepositStatus
from app.models.deposit import UnmatchedTransfer
from app.models.ledger import LedgerEntry
from app.repositories.account import AccountRepository
from app.repositories.deposit import DepositRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.wallet import WalletRepository
from app.services.deposit import DepositService
from app.services.deposit_provider import MockTRC20DepositProvider, OnChainTransactionDTO
from app.services.wallet import WalletService


def _tx(
    *,
    tx_hash: str,
    amount: Decimal,
    confirmations: int = 20,
    to_address: str | None = None,
    is_success: bool = True,
    asset_contract: str | None = None,
    event_index: int = 0,
    is_finalized: bool = True,
) -> OnChainTransactionDTO:
    return OnChainTransactionDTO(
        tx_hash=tx_hash,
        network=DepositNetwork.TRC20,
        asset_contract=asset_contract or settings.USDT_TRC20_CONTRACT_ADDRESS,
        from_address=f"T-sender-{uuid.uuid4().hex[:8]}",
        to_address=to_address or settings.USDT_TRC20_DEPOSIT_ADDRESS,
        amount=amount,
        confirmations=confirmations,
        is_success=is_success,
        timestamp=datetime.now(UTC),
        event_index=event_index,
        is_finalized=is_finalized,
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


async def test_scan_correlates_exact_match_and_credits(
    db_session: AsyncSession, make_account, make_wallet, make_deposit, make_deposit_service
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    deposit = await make_deposit(user, expected_amount=Decimal("50"), required_confirmations=20)

    provider = MockTRC20DepositProvider()
    provider.add_simulated_tx(_tx(tx_hash="tx-exact-1", amount=Decimal("50")))
    service = make_deposit_service(provider)

    processed = await service.scan_and_correlate_deposits()
    assert processed == 1

    await db_session.refresh(deposit)
    assert deposit.status == DepositStatus.CREDITED
    assert deposit.credited_amount == Decimal("50")

    ledger_entries = (
        await db_session.execute(
            select(LedgerEntry).where(LedgerEntry.reference_id == deposit.id)
        )
    ).scalars().all()
    assert len(ledger_entries) == 1


async def test_scan_creates_unmatched_transfer_when_no_waiting_deposit_matches(
    db_session: AsyncSession, make_deposit_service
):
    provider = MockTRC20DepositProvider()
    provider.add_simulated_tx(_tx(tx_hash="tx-unmatched-1", amount=Decimal("999")))
    service = make_deposit_service(provider)

    processed = await service.scan_and_correlate_deposits()
    assert processed == 0

    unmatched = (
        await db_session.execute(
            select(UnmatchedTransfer).where(UnmatchedTransfer.tx_hash == "tx-unmatched-1")
        )
    ).scalar_one()
    assert unmatched.correlation_status == CorrelationStatus.UNMATCHED


async def test_scan_creates_ambiguous_transfer_when_multiple_deposits_match(
    db_session: AsyncSession, make_account, make_wallet, make_deposit, make_deposit_service
):
    user_a = await make_account(role=UserRole.USER)
    await make_wallet(user_a)
    deposit_a = await make_deposit(user_a, expected_amount=Decimal("77"))

    user_b = await make_account(role=UserRole.USER)
    await make_wallet(user_b)
    deposit_b = await make_deposit(user_b, expected_amount=Decimal("77"))

    provider = MockTRC20DepositProvider()
    provider.add_simulated_tx(_tx(tx_hash="tx-ambiguous-1", amount=Decimal("77")))
    service = make_deposit_service(provider)

    processed = await service.scan_and_correlate_deposits()
    assert processed == 0

    unmatched = (
        await db_session.execute(
            select(UnmatchedTransfer).where(UnmatchedTransfer.tx_hash == "tx-ambiguous-1")
        )
    ).scalar_one()
    assert unmatched.correlation_status == CorrelationStatus.AMBIGUOUS

    await db_session.refresh(deposit_a)
    await db_session.refresh(deposit_b)
    assert deposit_a.status == DepositStatus.WAITING
    assert deposit_b.status == DepositStatus.WAITING


async def test_scan_skips_failed_transactions(
    db_session: AsyncSession, make_account, make_wallet, make_deposit, make_deposit_service
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    deposit = await make_deposit(user, expected_amount=Decimal("30"))

    provider = MockTRC20DepositProvider()
    provider.add_simulated_tx(_tx(tx_hash="tx-failed-1", amount=Decimal("30"), is_success=False))
    service = make_deposit_service(provider)

    processed = await service.scan_and_correlate_deposits()
    assert processed == 0

    await db_session.refresh(deposit)
    assert deposit.status == DepositStatus.WAITING


async def test_scan_skips_unfinalized_transactions(
    db_session: AsyncSession, make_account, make_wallet, make_deposit, make_deposit_service
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    deposit = await make_deposit(user, expected_amount=Decimal("30"))

    provider = MockTRC20DepositProvider()
    provider.add_simulated_tx(
        _tx(tx_hash="tx-unfinalized-1", amount=Decimal("30"), is_finalized=False)
    )

    assert await make_deposit_service(provider).scan_and_correlate_deposits() == 0
    await db_session.refresh(deposit)
    assert deposit.status == DepositStatus.WAITING


async def test_scan_skips_wrong_contract_address(
    db_session: AsyncSession, make_account, make_wallet, make_deposit, make_deposit_service
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    deposit = await make_deposit(user, expected_amount=Decimal("30"))

    provider = MockTRC20DepositProvider()
    provider.add_simulated_tx(
        _tx(tx_hash="tx-wrong-contract", amount=Decimal("30"), asset_contract="Tsomeothertoken")
    )
    service = make_deposit_service(provider)

    processed = await service.scan_and_correlate_deposits()
    assert processed == 0

    await db_session.refresh(deposit)
    assert deposit.status == DepositStatus.WAITING


async def test_scan_does_not_double_credit_when_run_twice_for_same_tx(
    db_session: AsyncSession, make_account, make_wallet, make_deposit, make_deposit_service
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    deposit = await make_deposit(user, expected_amount=Decimal("42"))

    provider = MockTRC20DepositProvider()
    provider.add_simulated_tx(_tx(tx_hash="tx-replay-1", amount=Decimal("42")))
    service = make_deposit_service(provider)

    await service.scan_and_correlate_deposits()
    await service.scan_and_correlate_deposits()

    await db_session.refresh(deposit)
    assert deposit.status == DepositStatus.CREDITED

    ledger_entries = (
        await db_session.execute(
            select(LedgerEntry).where(LedgerEntry.reference_id == deposit.id)
        )
    ).scalars().all()
    assert len(ledger_entries) == 1


async def test_scan_tracks_multiple_transfer_events_in_one_transaction(
    db_session: AsyncSession, make_account, make_wallet, make_deposit, make_deposit_service
):
    user_a = await make_account(role=UserRole.USER)
    await make_wallet(user_a)
    deposit_a = await make_deposit(user_a, expected_amount=Decimal("41"))
    user_b = await make_account(role=UserRole.USER)
    await make_wallet(user_b)
    deposit_b = await make_deposit(user_b, expected_amount=Decimal("42"))

    provider = MockTRC20DepositProvider()
    provider.add_simulated_tx(
        _tx(tx_hash="same-chain-tx", amount=Decimal("41"), event_index=3)
    )
    provider.add_simulated_tx(
        _tx(tx_hash="same-chain-tx", amount=Decimal("42"), event_index=4)
    )

    assert await make_deposit_service(provider).scan_and_correlate_deposits() == 2
    await db_session.refresh(deposit_a)
    await db_session.refresh(deposit_b)
    assert deposit_a.status == DepositStatus.CREDITED
    assert deposit_b.status == DepositStatus.CREDITED
    assert deposit_a.provider_event_id.endswith(":3")
    assert deposit_b.provider_event_id.endswith(":4")
