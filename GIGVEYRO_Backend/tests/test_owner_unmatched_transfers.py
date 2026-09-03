import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deposit import DepositNetwork, DepositStatus, ReconciliationStatus
from app.models.audit import AuditLog
from app.models.deposit import DepositReconciliationAction, UnmatchedTransfer
from app.models.ledger import LedgerEntry
from app.models.notification import Notification
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
        return DepositService(DepositRepository(db_session), account_repo, wallet_service, provider)

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


async def test_owner_filters_unmatched_by_reason(client, make_account, make_deposit_service):
    owner = await make_account(role=UserRole.OWNER)
    await _create_unmatched(make_deposit_service, tx_hash="tx-reason-filter")
    response = await client.get(
        "/owner/deposits/unmatched",
        params={"reason": "no waiting deposit"},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1


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


async def test_unmatched_deposit_mutations_are_explicit_and_limited():
    from app.main import app as fastapi_app

    schema = fastapi_app.openapi()
    paths = schema["paths"]
    assert set(paths["/owner/deposits/unmatched/{transfer_id}/link"]) == {"post"}
    assert set(paths["/owner/deposits/unmatched/{transfer_id}/reprocess"]) == {"post"}
    assert set(paths["/owner/deposits/unmatched/{transfer_id}/ignore"]) == {"post"}
    assert not any(
        "credit" in path for path in paths if path.startswith("/owner/deposits/unmatched")
    )


async def test_owner_links_finalized_transfer_through_authoritative_credit_path(
    client, db_session, make_account, make_wallet, make_deposit, make_deposit_service
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user)
    amount = Decimal("145.25")
    await _create_unmatched(make_deposit_service, tx_hash="tx-reconcile-exact", amount=amount)
    transfer = (
        await db_session.execute(
            select(UnmatchedTransfer).where(UnmatchedTransfer.tx_hash == "tx-reconcile-exact")
        )
    ).scalar_one()
    deposit = await make_deposit(user, expected_amount=amount)
    payload = {"deposit_id": str(deposit.id), "idempotency_key": "link-exact-0001"}

    first = await client.post(
        f"/owner/deposits/unmatched/{transfer.id}/link", json=payload, headers=_auth_headers(owner)
    )
    second = await client.post(
        f"/owner/deposits/unmatched/{transfer.id}/link", json=payload, headers=_auth_headers(owner)
    )

    assert first.status_code == 200
    assert first.json()["result_code"] == "CREDITED"
    assert first.json()["replayed"] is False
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    await db_session.refresh(wallet)
    await db_session.refresh(deposit)
    await db_session.refresh(transfer)
    assert wallet.available_balance == amount
    assert deposit.status == DepositStatus.CREDITED
    assert transfer.reconciliation_status == ReconciliationStatus.CREDITED
    assert transfer.linked_deposit_id == deposit.id
    ledger = (
        (
            await db_session.execute(
                select(LedgerEntry).where(LedgerEntry.reference_id == deposit.id)
            )
        )
        .scalars()
        .all()
    )
    actions = (
        (
            await db_session.execute(
                select(DepositReconciliationAction).where(
                    DepositReconciliationAction.transfer_id == transfer.id
                )
            )
        )
        .scalars()
        .all()
    )
    notifications = (
        (await db_session.execute(select(Notification).where(Notification.account_id == user.id)))
        .scalars()
        .all()
    )
    audits = (
        (
            await db_session.execute(
                select(AuditLog.action).where(AuditLog.entity_id == str(transfer.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(ledger) == 1
    assert len(actions) == 1
    assert [item.message_key for item in notifications] == ["deposit.credited"]
    assert "deposit_reconciliation.linked" in audits
    assert "deposit_reconciliation.credit_succeeded" in audits


async def test_reprocess_ambiguous_then_ignore_never_credits(
    client, db_session, make_account, make_wallet, make_deposit, make_deposit_service
):
    owner = await make_account(role=UserRole.OWNER)
    amount = Decimal("320")
    wallets = []
    for _ in range(2):
        user = await make_account(role=UserRole.USER)
        wallets.append(await make_wallet(user))
        await make_deposit(user, expected_amount=amount)
    await _create_unmatched(make_deposit_service, tx_hash="tx-reconcile-ambiguous", amount=amount)
    transfer = (
        await db_session.execute(
            select(UnmatchedTransfer).where(UnmatchedTransfer.tx_hash == "tx-reconcile-ambiguous")
        )
    ).scalar_one()

    reprocessed = await client.post(
        f"/owner/deposits/unmatched/{transfer.id}/reprocess",
        json={"idempotency_key": "reprocess-ambiguous-1"},
        headers=_auth_headers(owner),
    )
    ignored = await client.post(
        f"/owner/deposits/unmatched/{transfer.id}/ignore",
        json={
            "idempotency_key": "ignore-ambiguous-001",
            "reason": "Verified duplicate sender test",
        },
        headers=_auth_headers(owner),
    )

    assert reprocessed.status_code == 200
    assert reprocessed.json()["result_code"] == "AMBIGUOUS_MATCH"
    assert ignored.status_code == 200
    assert ignored.json()["result_code"] == "IGNORED"
    assert all(wallet.available_balance == Decimal("0") for wallet in wallets)
    assert not (await db_session.execute(select(LedgerEntry))).scalars().all()


@pytest.mark.parametrize("role", [UserRole.USER, UserRole.MERCHANT])
async def test_non_owner_cannot_mutate_unmatched_transfer(
    client, make_account, make_deposit_service, role
):
    actor = await make_account(role=role)
    await _create_unmatched(make_deposit_service, tx_hash=f"tx-forbidden-{role.value}")
    response = await client.post(
        f"/owner/deposits/unmatched/{uuid.uuid4()}/link",
        json={"deposit_id": str(uuid.uuid4()), "idempotency_key": "forbidden-owner-action"},
        headers=_auth_headers(actor),
    )
    assert response.status_code == 403


async def test_link_rejects_amount_mismatch_without_financial_mutation(
    client, db_session, make_account, make_wallet, make_deposit, make_deposit_service
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user)
    await _create_unmatched(
        make_deposit_service, tx_hash="tx-reconcile-mismatch", amount=Decimal("9")
    )
    transfer = (
        await db_session.execute(
            select(UnmatchedTransfer).where(UnmatchedTransfer.tx_hash == "tx-reconcile-mismatch")
        )
    ).scalar_one()
    deposit = await make_deposit(user, expected_amount=Decimal("10"))

    response = await client.post(
        f"/owner/deposits/unmatched/{transfer.id}/link",
        json={"deposit_id": str(deposit.id), "idempotency_key": "mismatch-link-0001"},
        headers=_auth_headers(owner),
    )
    retry = await client.post(
        f"/owner/deposits/unmatched/{transfer.id}/link",
        json={"deposit_id": str(deposit.id), "idempotency_key": "mismatch-link-0001"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 422
    assert retry.status_code == 422
    assert response.json()["detail"]["code"] == "AMOUNT_MISMATCH"
    assert wallet.available_balance == Decimal("0")
    assert not (await db_session.execute(select(LedgerEntry))).scalars().all()
    failure_audits = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.entity_id == str(transfer.id),
                    AuditLog.action == "deposit_reconciliation.credit_failed",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(failure_audits) == 1


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [("not_final", "TRANSFER_NOT_FINAL"), ("wrong_token", "TOKEN_MISMATCH")],
)
async def test_link_rejects_unsafe_chain_facts(
    client,
    db_session,
    make_account,
    make_wallet,
    make_deposit,
    make_deposit_service,
    mutation,
    expected_code,
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user)
    await _create_unmatched(make_deposit_service, tx_hash=f"tx-{mutation}", amount=Decimal("12"))
    transfer = (
        await db_session.execute(
            select(UnmatchedTransfer).where(UnmatchedTransfer.tx_hash == f"tx-{mutation}")
        )
    ).scalar_one()
    if mutation == "not_final":
        transfer.is_finalized = False
    else:
        transfer.asset_contract = "TWrongTokenContract"
    deposit = await make_deposit(user, expected_amount=Decimal("12"))

    response = await client.post(
        f"/owner/deposits/unmatched/{transfer.id}/link",
        json={"deposit_id": str(deposit.id), "idempotency_key": f"unsafe-{mutation}-key"},
        headers=_auth_headers(owner),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == expected_code
    assert wallet.available_balance == Decimal("0")


async def test_link_rejects_expired_deposit(
    client, db_session, make_account, make_wallet, make_deposit, make_deposit_service
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user)
    await _create_unmatched(make_deposit_service, tx_hash="tx-expired-link", amount=Decimal("18"))
    transfer = (
        await db_session.execute(
            select(UnmatchedTransfer).where(UnmatchedTransfer.tx_hash == "tx-expired-link")
        )
    ).scalar_one()
    deposit = await make_deposit(user, expected_amount=Decimal("18"), expires_in_minutes=-1)
    response = await client.post(
        f"/owner/deposits/unmatched/{transfer.id}/link",
        json={"deposit_id": str(deposit.id), "idempotency_key": "expired-link-key"},
        headers=_auth_headers(owner),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "DEPOSIT_EXPIRED"
    assert wallet.available_balance == Decimal("0")


async def test_reprocess_exact_uses_credit_path_and_no_match_stays_nonfinancial(
    client, db_session, make_account, make_wallet, make_deposit, make_deposit_service
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user)
    await _create_unmatched(
        make_deposit_service, tx_hash="tx-reprocess-exact", amount=Decimal("27")
    )
    exact = (
        await db_session.execute(
            select(UnmatchedTransfer).where(UnmatchedTransfer.tx_hash == "tx-reprocess-exact")
        )
    ).scalar_one()
    await make_deposit(user, expected_amount=Decimal("27"))
    exact_response = await client.post(
        f"/owner/deposits/unmatched/{exact.id}/reprocess",
        json={"idempotency_key": "reprocess-exact-key"},
        headers=_auth_headers(owner),
    )
    assert exact_response.status_code == 200
    assert exact_response.json()["result_code"] == "CREDITED"
    await db_session.refresh(wallet)
    assert wallet.available_balance == Decimal("27")

    await _create_unmatched(
        make_deposit_service, tx_hash="tx-reprocess-none", amount=Decimal("999")
    )
    no_match = (
        await db_session.execute(
            select(UnmatchedTransfer).where(UnmatchedTransfer.tx_hash == "tx-reprocess-none")
        )
    ).scalar_one()
    no_match_response = await client.post(
        f"/owner/deposits/unmatched/{no_match.id}/reprocess",
        json={"idempotency_key": "reprocess-no-match"},
        headers=_auth_headers(owner),
    )
    assert no_match_response.status_code == 200
    assert no_match_response.json()["result_code"] == "NO_MATCH"
    assert no_match_response.json()["transfer"]["reconciliation_status"] == "REPROCESSED"
