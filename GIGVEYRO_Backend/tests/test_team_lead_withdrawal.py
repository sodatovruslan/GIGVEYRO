from decimal import Decimal

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.wallet import LedgerEntryType


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _create(client, team_lead, amount: str = "20") -> dict:
    response = await client.post(
        "/team-lead/withdrawals",
        json={
            "amount": amount,
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(team_lead),
    )
    assert response.status_code == 201
    return response.json()


# ---- CREATE -----------------------------------------------------------


async def test_team_lead_creates_withdrawal(client, make_account, make_wallet):
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(team_lead, available=Decimal("10"))

    body = await _create(client, team_lead, amount="6")
    assert body["status"] == "pending"
    assert body["amount"] == "6.00000000"
    assert body["public_id"].startswith("TLW-")


async def test_withdrawal_holds_funds_from_available_balance(client, make_account, make_wallet):
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(team_lead, available=Decimal("10"))

    await _create(client, team_lead, amount="4")

    wallet_response = await client.get(
        f"/owner/accounts/{team_lead.id}/wallet",
        headers=_auth_headers(await make_account(role=UserRole.OWNER)),
    )
    assert wallet_response.json()["available_balance"] == "6.00000000"
    assert wallet_response.json()["frozen_balance"] == "4.00000000"


async def test_withdrawal_rejects_insufficient_profit(client, make_account, make_wallet):
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(team_lead, available=Decimal("1"))

    response = await client.post(
        "/team-lead/withdrawals",
        json={
            "amount": "5",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(team_lead),
    )
    assert response.status_code == 400


async def test_inactive_team_lead_cannot_create_withdrawal(client, make_account, make_wallet):
    """A blocked account can't even authenticate - the same 401 the rest of
    the app already returns for any blocked account on any endpoint, not a
    withdrawal-specific check."""
    team_lead = await make_account(role=UserRole.TEAM_LEAD, is_active=False)
    await make_wallet(team_lead, available=Decimal("10"))

    response = await client.post(
        "/team-lead/withdrawals",
        json={
            "amount": "5",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(team_lead),
    )
    assert response.status_code == 401


async def test_user_cannot_create_team_lead_withdrawal(client, make_account):
    user = await make_account(role=UserRole.USER)
    response = await client.post(
        "/team-lead/withdrawals",
        json={
            "amount": "5",
            "destination_type": "usdt_trc20_address",
            "destination": "T" + "a" * 33,
        },
        headers=_auth_headers(user),
    )
    assert response.status_code == 403


# ---- IDOR / ISOLATION ---------------------------------------------------


async def test_team_lead_cannot_see_another_team_leads_withdrawal(client, make_account, make_wallet):
    lead_a = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(lead_a, available=Decimal("10"))
    lead_b = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(lead_b, available=Decimal("10"))

    created = await _create(client, lead_a, amount="5")

    response = await client.get(
        f"/team-lead/withdrawals/{created['id']}", headers=_auth_headers(lead_b)
    )
    assert response.status_code == 404


async def test_team_lead_cannot_cancel_another_team_leads_withdrawal(
    client, make_account, make_wallet
):
    lead_a = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(lead_a, available=Decimal("10"))
    lead_b = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(lead_b, available=Decimal("10"))

    created = await _create(client, lead_a, amount="5")

    response = await client.post(
        f"/team-lead/withdrawals/{created['id']}/cancel", headers=_auth_headers(lead_b)
    )
    assert response.status_code == 404


# ---- CANCEL --------------------------------------------------------------


async def test_team_lead_cancels_pending_withdrawal_and_funds_released(
    client, make_account, make_wallet
):
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(team_lead, available=Decimal("10"))
    created = await _create(client, team_lead, amount="6")

    response = await client.post(
        f"/team-lead/withdrawals/{created['id']}/cancel", headers=_auth_headers(team_lead)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    owner = await make_account(role=UserRole.OWNER)
    wallet_response = await client.get(
        f"/owner/accounts/{team_lead.id}/wallet", headers=_auth_headers(owner)
    )
    assert wallet_response.json()["available_balance"] == "10.00000000"
    assert wallet_response.json()["frozen_balance"] == "0.00000000"


# ---- OWNER APPROVAL / REJECTION / PAID LIFECYCLE --------------------------


async def test_owner_approves_and_marks_paid(client, make_account, make_wallet):
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(team_lead, available=Decimal("10"))
    owner = await make_account(role=UserRole.OWNER)
    created = await _create(client, team_lead, amount="6")

    approve = await client.post(
        f"/owner/team-lead-withdrawals/{created['id']}/approve", headers=_auth_headers(owner)
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    paid = await client.post(
        f"/owner/team-lead-withdrawals/{created['id']}/mark-paid", headers=_auth_headers(owner)
    )
    assert paid.status_code == 200
    assert paid.json()["status"] == "paid"

    wallet_response = await client.get(
        f"/owner/accounts/{team_lead.id}/wallet", headers=_auth_headers(owner)
    )
    assert wallet_response.json()["available_balance"] == "4.00000000"
    assert wallet_response.json()["frozen_balance"] == "0.00000000"


async def test_owner_rejects_and_releases_funds(client, make_account, make_wallet):
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(team_lead, available=Decimal("10"))
    owner = await make_account(role=UserRole.OWNER)
    created = await _create(client, team_lead, amount="6")

    reject = await client.post(
        f"/owner/team-lead-withdrawals/{created['id']}/reject", headers=_auth_headers(owner)
    )
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"

    wallet_response = await client.get(
        f"/owner/accounts/{team_lead.id}/wallet", headers=_auth_headers(owner)
    )
    assert wallet_response.json()["available_balance"] == "10.00000000"
    assert wallet_response.json()["frozen_balance"] == "0.00000000"


async def test_team_lead_cannot_approve_own_withdrawal(client, make_account, make_wallet):
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(team_lead, available=Decimal("10"))
    created = await _create(client, team_lead, amount="6")

    response = await client.post(
        f"/team-lead/withdrawals/{created['id']}/approve", headers=_auth_headers(team_lead)
    )
    assert response.status_code == 404  # no such route under the team-lead router at all


async def test_pending_withdrawal_cannot_be_paid_directly(client, make_account, make_wallet):
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(team_lead, available=Decimal("10"))
    owner = await make_account(role=UserRole.OWNER)
    created = await _create(client, team_lead, amount="6")

    response = await client.post(
        f"/owner/team-lead-withdrawals/{created['id']}/mark-paid", headers=_auth_headers(owner)
    )
    assert response.status_code == 400


async def test_paid_withdrawal_cannot_be_paid_again(client, make_account, make_wallet):
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(team_lead, available=Decimal("10"))
    owner = await make_account(role=UserRole.OWNER)
    created = await _create(client, team_lead, amount="6")
    await client.post(
        f"/owner/team-lead-withdrawals/{created['id']}/approve", headers=_auth_headers(owner)
    )
    first = await client.post(
        f"/owner/team-lead-withdrawals/{created['id']}/mark-paid", headers=_auth_headers(owner)
    )
    second = await client.post(
        f"/owner/team-lead-withdrawals/{created['id']}/mark-paid", headers=_auth_headers(owner)
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "paid"


async def test_paid_withdrawal_creates_exactly_one_ledger_entry(
    client, make_account, make_wallet, db_session
):
    from sqlalchemy import select

    from app.models.ledger import LedgerEntry

    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(team_lead, available=Decimal("10"))
    owner = await make_account(role=UserRole.OWNER)
    created = await _create(client, team_lead, amount="6")
    await client.post(
        f"/owner/team-lead-withdrawals/{created['id']}/approve", headers=_auth_headers(owner)
    )
    await client.post(
        f"/owner/team-lead-withdrawals/{created['id']}/mark-paid", headers=_auth_headers(owner)
    )

    entries = (
        await db_session.execute(
            select(LedgerEntry).where(
                LedgerEntry.reference_type == "withdrawal",
                LedgerEntry.reference_id == created["id"],
                LedgerEntry.type == LedgerEntryType.WITHDRAWAL_PAID,
            )
        )
    ).scalars().all()
    assert len(entries) == 1


async def test_owner_lists_all_team_lead_withdrawals(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    lead_a = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(lead_a, available=Decimal("10"))
    lead_b = await make_account(role=UserRole.TEAM_LEAD)
    await make_wallet(lead_b, available=Decimal("10"))
    await _create(client, lead_a, amount="3")
    await _create(client, lead_b, amount="4")

    response = await client.get("/owner/team-lead-withdrawals", headers=_auth_headers(owner))
    assert response.status_code == 200
    assert response.json()["total"] == 2


# ---- CONCURRENCY: TWO WITHDRAWALS CANNOT SPEND THE SAME PROFIT -------------


async def test_concurrent_withdrawals_cannot_overspend_available_profit():
    import asyncio
    import uuid

    from app.core.security import hash_password
    from app.db.session import AsyncSessionLocal
    from app.enums.withdrawal import WithdrawalDestinationType
    from app.models.account import Account
    from app.models.ledger import LedgerEntry
    from app.models.wallet import UserWallet
    from app.repositories.account import AccountRepository
    from app.repositories.ledger import LedgerRepository
    from app.repositories.team_lead_withdrawal import TeamLeadWithdrawalRepository
    from app.repositories.wallet import WalletRepository
    from app.services.team_lead_withdrawal import TeamLeadWithdrawalService
    from app.services.wallet import InsufficientBalanceError, WalletService

    async with AsyncSessionLocal() as setup_session:
        account_repo = AccountRepository(setup_session)
        wallet_repo = WalletRepository(setup_session)
        team_lead = Account(
            username=f"tl_race_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("RaceTeamLead123"),
            role=UserRole.TEAM_LEAD,
            full_name="Race Team Lead",
            is_active=True,
        )
        await account_repo.create(team_lead)
        wallet = UserWallet(account_id=team_lead.id, available_balance=Decimal("10"))
        await wallet_repo.create(wallet)
        await setup_session.commit()
        team_lead_id = team_lead.id

    async def try_withdraw(amount: Decimal) -> str:
        async with AsyncSessionLocal() as session:
            account_repo = AccountRepository(session)
            account = await account_repo.get_by_id(team_lead_id)
            wallet_service = WalletService(WalletRepository(session), LedgerRepository(session), account_repo)
            service = TeamLeadWithdrawalService(
                withdrawal_repository=TeamLeadWithdrawalRepository(session),
                wallet_service=wallet_service,
                account_repository=account_repo,
            )
            try:
                await service.create_withdrawal(
                    account,
                    amount=amount,
                    destination_type=WithdrawalDestinationType.USDT_TRC20_ADDRESS,
                    destination="T" + "a" * 33,
                )
                await session.commit()
                return "won"
            except InsufficientBalanceError:
                await session.rollback()
                return "lost"

    try:
        results = await asyncio.gather(try_withdraw(Decimal("7")), try_withdraw(Decimal("7")))
        # Two 7s against an available balance of 10 - both cannot win, since
        # that would require withdrawing 14 from a 10 balance.
        assert results.count("won") == 1
        assert results.count("lost") == 1

        async with AsyncSessionLocal() as verify_session:
            wallet = await WalletRepository(verify_session).get_by_account_id(team_lead_id)
            assert wallet.available_balance == Decimal("3")
            assert wallet.frozen_balance == Decimal("7")
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            from sqlalchemy import delete

            from app.models.team_lead_withdrawal import TeamLeadWithdrawal

            await cleanup_session.execute(
                delete(LedgerEntry).where(LedgerEntry.account_id == team_lead_id)
            )
            await cleanup_session.execute(
                delete(TeamLeadWithdrawal).where(TeamLeadWithdrawal.team_lead_id == team_lead_id)
            )
            await cleanup_session.execute(
                delete(UserWallet).where(UserWallet.account_id == team_lead_id)
            )
            await cleanup_session.execute(delete(Account).where(Account.id == team_lead_id))
            await cleanup_session.commit()
