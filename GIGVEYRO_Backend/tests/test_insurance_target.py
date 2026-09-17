"""Fixed per-user insurance target: deposit-time insurance-first allocation,
atomicity/concurrency of both deposits and manual decreases, Owner target
CRUD (audit, RBAC, validation, no side effects on the balances themselves),
and explicit proof that every OTHER wallet-mutating flow leaves insurance
untouched. Replaces the retired percentage/high-water-mark model
(tests/test_insurance_reserve.py, deleted) - migration 0037's
insurance_reserve_basis column and insurance_reserve_policies table remain
in the schema as inert history, but nothing here exercises them anymore."""

import asyncio
import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.core.security import create_access_token, hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.models.account import Account
from app.models.audit import AuditLog
from app.models.ledger import LedgerEntry
from app.models.wallet import UserWallet
from app.repositories.account import AccountRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.wallet import WalletRepository
from app.schemas.wallet import InsuranceTargetUpdateRequest
from app.services.wallet import (
    InsufficientInsuranceReserveError,
    WalletService,
)


def _headers(account) -> dict:
    return {"Authorization": f"Bearer {create_access_token(account.id, account.role.value)}"}


# ---------------------------------------------------------------------------
# Deposit allocation: insurance fills first, remainder to available
# ---------------------------------------------------------------------------


async def test_deposit_fills_insurance_gap_then_available(
    db_session, make_account, make_wallet
):
    """The Owner's own worked example, verbatim: target=500, three deposits
    in sequence - +300 (fully absorbed), +400 (fills the remaining 200 gap,
    200 spills to available), +1000 (insurance already at target, all goes
    to available)."""
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, insurance_target=Decimal("500"))
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )

    await service.credit_deposit(account_id=user.id, amount=Decimal("300"), deposit_id=uuid.uuid4())
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("300.00000000")
    assert wallet.available_balance == Decimal("0.00000000")

    await service.credit_deposit(account_id=user.id, amount=Decimal("400"), deposit_id=uuid.uuid4())
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("500.00000000")
    assert wallet.available_balance == Decimal("200.00000000")

    await service.credit_deposit(account_id=user.id, amount=Decimal("1000"), deposit_id=uuid.uuid4())
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("500.00000000")
    assert wallet.available_balance == Decimal("1200.00000000")


async def test_deposit_splits_across_existing_partial_insurance(
    db_session, make_account, make_wallet
):
    """target=1000, insurance already at 400 (partial), deposit +700 ->
    insurance reaches exactly 1000, the remaining 100 goes to available."""
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(
        user, insurance=Decimal("400"), insurance_target=Decimal("1000")
    )
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )

    await service.credit_deposit(account_id=user.id, amount=Decimal("700"), deposit_id=uuid.uuid4())
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("1000.00000000")
    assert wallet.available_balance == Decimal("100.00000000")


async def test_deposit_with_zero_target_behaves_as_before(db_session, make_account, make_wallet):
    """No target ever set (defaults to 0) - the gap is always 0, so every
    deposit goes entirely to available, identical to the pre-existing
    behaviour before insurance-first allocation was introduced."""
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, insurance=Decimal("5"))
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )

    await service.credit_deposit(account_id=user.id, amount=Decimal("30"), deposit_id=uuid.uuid4())
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("5.00000000")
    assert wallet.available_balance == Decimal("30.00000000")


async def test_deposit_split_is_idempotent_and_a_single_ledger_row(
    db_session, make_account, make_wallet
):
    """A retried deposit credit (same deposit_id) must not double-apply, and
    the split is fully reconstructible from exactly one ledger row - no
    second row for the insurance portion."""
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, insurance_target=Decimal("500"))
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )
    deposit_id = uuid.uuid4()

    first = await service.credit_deposit(account_id=user.id, amount=Decimal("700"), deposit_id=deposit_id)
    second = await service.credit_deposit(account_id=user.id, amount=Decimal("700"), deposit_id=deposit_id)
    assert first.id == second.id

    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("500.00000000")
    assert wallet.available_balance == Decimal("200.00000000")

    entries = (
        (await db_session.execute(select(LedgerEntry).where(LedgerEntry.reference_id == deposit_id)))
        .scalars()
        .all()
    )
    assert len(entries) == 1, "exactly one ledger row per deposit, even when it splits two buckets"
    entry = entries[0]
    assert entry.amount == Decimal("700.00000000")
    assert entry.insurance_after - entry.insurance_before == Decimal("500.00000000")
    assert entry.available_after - entry.available_before == Decimal("200.00000000")


async def test_target_increase_does_not_move_money(db_session, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    owner = await make_account(role=UserRole.OWNER)
    wallet = await make_wallet(
        user, insurance=Decimal("500"), available=Decimal("50"), insurance_target=Decimal("500")
    )
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )
    await service.set_insurance_target(actor=owner, target_account_id=user.id, new_target=Decimal("1000"))
    await db_session.refresh(wallet)
    assert wallet.insurance_target == Decimal("1000.00000000")
    assert wallet.insurance_balance == Decimal("500.00000000"), "raising the target alone moves no money"
    assert wallet.available_balance == Decimal("50.00000000")


async def test_target_decrease_does_not_move_money(db_session, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    owner = await make_account(role=UserRole.OWNER)
    wallet = await make_wallet(user, insurance=Decimal("1000"), insurance_target=Decimal("1000"))
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )
    await service.set_insurance_target(actor=owner, target_account_id=user.id, new_target=Decimal("500"))
    await db_session.refresh(wallet)
    assert wallet.insurance_target == Decimal("500.00000000")
    assert wallet.insurance_balance == Decimal("1000.00000000"), (
        "lowering the target alone does not claw back the existing insurance balance"
    )


# ---------------------------------------------------------------------------
# Insurance decrease protection: can never go below target
# ---------------------------------------------------------------------------


async def test_default_target_is_zero_and_changes_nothing(client, make_account, make_wallet):
    """Safe default: a wallet with no target ever set can still have its
    insurance decreased freely, exactly as before this feature existed."""
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, insurance=Decimal("100"))
    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "-90", "description": "drawdown", "idempotency_key": "default-safe-1"},
        headers=_headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["insurance_balance"] == "10.00000000"


async def test_decrease_exactly_at_target_is_allowed(client, db_session, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, insurance=Decimal("1000"), insurance_target=Decimal("100"))

    # Rule is strictly "<", not "<=" - landing exactly on the target is fine.
    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "-900", "description": "to the edge", "idempotency_key": "edge-1"},
        headers=_headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["insurance_balance"] == "100.00000000"


async def test_decrease_below_target_is_denied_with_no_side_effects(
    client, db_session, make_account, make_wallet
):
    """The Owner's own example: insurance=500=target, attempt to debit 1 ->
    rejected, insurance stays 500, no ledger row, no balance side effect."""
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, insurance=Decimal("500"), insurance_target=Decimal("500"))

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "-1", "description": "over the edge", "idempotency_key": "deny-1"},
        headers=_headers(owner),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "INSUFFICIENT_INSURANCE_RESERVE"

    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("500.00000000"), "balance must be untouched"

    entries = (
        (await db_session.execute(select(LedgerEntry).where(LedgerEntry.idempotency_key == "deny-1")))
        .scalars()
        .all()
    )
    assert entries == [], "no ledger entry may exist for a denied operation"

    denied_audit = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "wallet.insurance_reserve_denied")
            )
        )
        .scalars()
        .all()
    )
    assert len(denied_audit) == 1
    assert denied_audit[0].entity_id == str(user.id)


async def test_decrease_that_stays_above_target_succeeds(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, insurance=Decimal("1000"), insurance_target=Decimal("100"))

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "-500", "description": "safe drawdown", "idempotency_key": "safe-1"},
        headers=_headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["insurance_balance"] == "500.00000000"


async def test_same_idempotency_key_retried_after_success_is_a_no_op(
    client, db_session, make_account, make_wallet
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, insurance=Decimal("1000"), insurance_target=Decimal("100"))

    first = await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "-500", "description": "drawdown", "idempotency_key": "retry-key-1"},
        headers=_headers(owner),
    )
    second = await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "-500", "description": "drawdown", "idempotency_key": "retry-key-1"},
        headers=_headers(owner),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("500.00000000"), "must not apply twice"


# ---------------------------------------------------------------------------
# Owner API: GET/PATCH insurance-target
# ---------------------------------------------------------------------------


async def test_get_insurance_target_view_reports_real_numbers(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, insurance=Decimal("300"), insurance_target=Decimal("500"))

    response = await client.get(f"/owner/accounts/{user.id}/wallet/insurance-target", headers=_headers(owner))
    assert response.status_code == 200
    body = response.json()
    assert body["insurance_balance"] == "300.00000000"
    assert body["insurance_target"] == "500.00000000"
    assert body["remaining_to_target"] == "200.00000000"


async def test_remaining_to_target_never_negative_once_above_target(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, insurance=Decimal("600"), insurance_target=Decimal("500"))

    response = await client.get(f"/owner/accounts/{user.id}/wallet/insurance-target", headers=_headers(owner))
    assert Decimal(response.json()["remaining_to_target"]) == Decimal("0")


async def test_owner_can_set_insurance_target(client, db_session, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user)

    response = await client.patch(
        f"/owner/accounts/{user.id}/wallet/insurance-target",
        json={"insurance_target": "1000"},
        headers=_headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["insurance_target"] == "1000.00000000"
    await db_session.refresh(wallet)
    assert wallet.insurance_target == Decimal("1000.00000000")


async def test_insurance_target_update_is_audited(client, db_session, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, insurance_target=Decimal("500"))

    response = await client.patch(
        f"/owner/accounts/{user.id}/wallet/insurance-target",
        json={"insurance_target": "1000"},
        headers=_headers(owner),
    )
    assert response.status_code == 200

    audit = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "wallet.insurance_target_changed")
            )
        )
        .scalars()
        .one()
    )
    assert audit.entity_id == str(user.id)
    assert audit.actor_account_id == owner.id
    assert Decimal(audit.audit_metadata["old_target"]) == Decimal("500")
    assert Decimal(audit.audit_metadata["new_target"]) == Decimal("1000")


async def test_changing_target_never_touches_balances_or_ledger(client, db_session, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(
        user, insurance=Decimal("300"), available=Decimal("40"), insurance_target=Decimal("500")
    )
    before_count = (
        await db_session.execute(select(LedgerEntry).where(LedgerEntry.account_id == user.id))
    ).scalars().all()

    response = await client.patch(
        f"/owner/accounts/{user.id}/wallet/insurance-target",
        json={"insurance_target": "800"},
        headers=_headers(owner),
    )
    assert response.status_code == 200

    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("300.00000000")
    assert wallet.available_balance == Decimal("40.00000000")
    after_count = (
        await db_session.execute(select(LedgerEntry).where(LedgerEntry.account_id == user.id))
    ).scalars().all()
    assert len(after_count) == len(before_count), "changing the target must never create a ledger entry"


async def test_non_owner_cannot_read_or_change_target(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    other_user = await make_account(role=UserRole.USER)
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_wallet(user)
    for account in (user, merchant):
        assert (
            await client.get(f"/owner/accounts/{user.id}/wallet/insurance-target", headers=_headers(account))
        ).status_code == 403
        assert (
            await client.patch(
                f"/owner/accounts/{user.id}/wallet/insurance-target",
                json={"insurance_target": "100"},
                headers=_headers(account),
            )
        ).status_code == 403
    # A USER attempting this against another USER's wallet is blocked by the
    # same 403 role check before account identity is even considered - the
    # IDOR angle is covered by the RBAC gate itself, not a separate branch.
    assert (
        await client.patch(
            f"/owner/accounts/{other_user.id}/wallet/insurance-target",
            json={"insurance_target": "100"},
            headers=_headers(user),
        )
    ).status_code == 403


async def test_negative_target_rejected(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    response = await client.patch(
        f"/owner/accounts/{user.id}/wallet/insurance-target",
        json={"insurance_target": "-1"},
        headers=_headers(owner),
    )
    assert response.status_code == 422


def test_float_input_is_rejected_by_schema():
    with pytest.raises(ValidationError, match="float"):
        InsuranceTargetUpdateRequest(insurance_target=10.5)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_input_is_rejected_by_schema(value):
    with pytest.raises(ValidationError):
        InsuranceTargetUpdateRequest(insurance_target=value)


async def test_target_update_for_inactive_account_rejected(client, make_account, make_wallet):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER, is_active=False)
    await make_wallet(user)
    response = await client.patch(
        f"/owner/accounts/{user.id}/wallet/insurance-target",
        json={"insurance_target": "100"},
        headers=_headers(owner),
    )
    assert response.status_code == 409


async def test_target_update_for_nonexistent_account_rejected(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    response = await client.patch(
        f"/owner/accounts/{uuid.uuid4()}/wallet/insurance-target",
        json={"insurance_target": "100"},
        headers=_headers(owner),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


async def test_concurrent_deposits_near_target_split_correctly():
    """target=500, insurance=400, two concurrent +100 deposits. The row lock
    on credit_deposit must serialize them: whichever commits first fills the
    remaining 100 gap and pushes 0 to available; the second sees the
    post-first insurance_balance already at target and pushes its full 100
    to available. Final state must be insurance=500, available=100 - never
    insurance=600 (double-counted gap) and never insurance=500/available=0
    (lost update)."""
    async with AsyncSessionLocal() as setup_session:
        account_repo = AccountRepository(setup_session)
        wallet_repo = WalletRepository(setup_session)

        user = Account(
            username=f"ins_dep_conc_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyTest123"),
            role=UserRole.USER,
            full_name="Insurance Deposit Concurrency User",
            is_active=True,
        )
        await account_repo.create(user)

        wallet = UserWallet(
            account_id=user.id,
            insurance_balance=Decimal("400"),
            insurance_target=Decimal("500"),
        )
        await wallet_repo.create(wallet)

        await setup_session.commit()
        user_id = user.id

    async def run_deposit(deposit_id: uuid.UUID) -> None:
        async with AsyncSessionLocal() as session:
            service = WalletService(
                WalletRepository(session), LedgerRepository(session), AccountRepository(session)
            )
            await service.credit_deposit(account_id=user_id, amount=Decimal("100"), deposit_id=deposit_id)
            await session.commit()

    try:
        await asyncio.gather(run_deposit(uuid.uuid4()), run_deposit(uuid.uuid4()))

        async with AsyncSessionLocal() as verify_session:
            final = await WalletRepository(verify_session).get_by_account_id(user_id)
            assert final.insurance_balance == Decimal("500.00000000")
            assert final.available_balance == Decimal("100.00000000")
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            await cleanup_session.execute(delete(LedgerEntry).where(LedgerEntry.account_id == user_id))
            await cleanup_session.execute(delete(UserWallet).where(UserWallet.account_id == user_id))
            await cleanup_session.execute(delete(Account).where(Account.id == user_id))
            await cleanup_session.commit()


async def test_concurrent_decreases_cannot_jointly_breach_the_target():
    """insurance=1000, target=100. Two concurrent -500 decreases would
    jointly leave -0 (breach); the row lock must serialize them so only one
    succeeds and the other is denied, never both applied."""
    async with AsyncSessionLocal() as setup_session:
        account_repo = AccountRepository(setup_session)
        wallet_repo = WalletRepository(setup_session)

        user = Account(
            username=f"ins_conc_user_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyTest123"),
            role=UserRole.USER,
            full_name="Insurance Concurrency User",
            is_active=True,
        )
        await account_repo.create(user)
        owner = Account(
            username=f"ins_conc_owner_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("ConcurrencyOwner123"),
            role=UserRole.OWNER,
            full_name="Insurance Concurrency Owner",
            is_active=True,
        )
        await account_repo.create(owner)

        wallet = UserWallet(
            account_id=user.id,
            insurance_balance=Decimal("1000"),
            insurance_target=Decimal("100"),
        )
        await wallet_repo.create(wallet)

        await setup_session.commit()
        user_id, owner_id = user.id, owner.id

    async def run_decrease(idempotency_key: str) -> str:
        async with AsyncSessionLocal() as session:
            actor = await AccountRepository(session).get_by_id(owner_id)
            service = WalletService(
                WalletRepository(session), LedgerRepository(session), AccountRepository(session)
            )
            try:
                await service.adjust_insurance(
                    actor=actor,
                    target_account_id=user_id,
                    amount=Decimal("-500"),
                    description="concurrent decrease",
                    idempotency_key=idempotency_key,
                )
                await session.commit()
                return "succeeded"
            except InsufficientInsuranceReserveError:
                await session.rollback()
                return "denied"

    try:
        results = await asyncio.gather(run_decrease("conc-ins-1"), run_decrease("conc-ins-2"))
        assert sorted(results) == ["denied", "succeeded"], (
            "exactly one of the two concurrent decreases must succeed"
        )

        async with AsyncSessionLocal() as verify_session:
            final = await WalletRepository(verify_session).get_by_account_id(user_id)
            assert final.insurance_balance == Decimal("500.00000000"), (
                "only one -500 decrease may have been applied"
            )
            assert final.insurance_balance >= Decimal("100"), (
                "the target floor must never be breached even under concurrency"
            )
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            await cleanup_session.execute(
                delete(LedgerEntry).where(LedgerEntry.account_id == user_id)
            )
            await cleanup_session.execute(
                delete(AuditLog).where(AuditLog.actor_account_id.in_([user_id, owner_id]))
            )
            await cleanup_session.execute(
                delete(UserWallet).where(UserWallet.account_id == user_id)
            )
            await cleanup_session.execute(
                delete(Account).where(Account.id.in_([user_id, owner_id]))
            )
            await cleanup_session.commit()


# ---------------------------------------------------------------------------
# Proof: every OTHER wallet-mutating path leaves insurance untouched
# ---------------------------------------------------------------------------


async def test_deal_freeze_and_release_never_touch_insurance(db_session, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, available=Decimal("100"), insurance=Decimal("42"))
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )
    deal_id = uuid.uuid4()
    await service.freeze_for_deal(account_id=user.id, amount=Decimal("50"), deal_id=deal_id)
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("42.00000000")

    await service.release_for_deal(user_account_id=user.id, amount=Decimal("50"), deal_id=deal_id)
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("42.00000000")


async def test_user_withdrawal_hold_release_pay_never_touch_insurance(
    db_session, make_account, make_wallet
):
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, available=Decimal("100"), insurance=Decimal("17"))
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )
    withdrawal_id = uuid.uuid4()
    await service.hold_for_user_withdrawal(
        user_id=user.id, amount=Decimal("40"), withdrawal_id=withdrawal_id
    )
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("17.00000000")

    await service.release_for_user_withdrawal(
        user_id=user.id, amount=Decimal("40"), withdrawal_id=withdrawal_id, actor_id=user.id
    )
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("17.00000000")


async def test_settle_deal_never_touches_user_insurance(
    db_session, make_account, make_wallet, make_merchant_wallet
):
    user = await make_account(role=UserRole.USER)
    merchant = await make_account(role=UserRole.MERCHANT)
    wallet = await make_wallet(user, available=Decimal("200"), insurance=Decimal("9"))
    await make_merchant_wallet(merchant)
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )
    deal_id = uuid.uuid4()
    await service.freeze_for_deal(account_id=user.id, amount=Decimal("100"), deal_id=deal_id)
    await service.settle_deal(
        user_account_id=user.id,
        merchant_account_id=merchant.id,
        amount=Decimal("100"),
        merchant_amount=Decimal("83"),
        user_profit_amount=Decimal("10"),
        deal_id=deal_id,
    )
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("9.00000000")


async def test_team_lead_profit_credit_never_touches_insurance(
    db_session, make_account, make_wallet
):
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    wallet = await make_wallet(team_lead, insurance=Decimal("6"))
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )
    await service.credit_team_lead_profit(
        team_lead_account_id=team_lead.id, amount=Decimal("1.5"), deal_id=uuid.uuid4()
    )
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("6.00000000")


async def test_manual_adjust_and_allocate_use_available_bucket_never_insurance(
    db_session, make_account, make_wallet
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, insurance=Decimal("8"))
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )
    await service.allocate(
        actor=owner,
        target_account_id=user.id,
        amount=Decimal("10"),
        description="d",
        idempotency_key="proof-allocate-1",
    )
    await service.manual_adjust(
        actor=owner,
        target_account_id=user.id,
        amount=Decimal("-3"),
        reason="r",
        idempotency_key="proof-adjust-1",
    )
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("8.00000000")
