"""Minimum insurance reserve: policy CRUD/validation, per-wallet high-water-
mark enforcement, atomicity/concurrency, audit trail, and explicit proof
that every OTHER wallet-mutating flow leaves insurance_balance untouched."""

import asyncio
import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select, update

from app.core.security import create_access_token, hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.models.account import Account
from app.models.audit import AuditLog
from app.models.insurance_reserve import InsuranceReservePolicy
from app.models.ledger import LedgerEntry
from app.models.wallet import UserWallet
from app.repositories.account import AccountRepository
from app.repositories.insurance_reserve import InsuranceReservePolicyRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.wallet import WalletRepository
from app.schemas.insurance_reserve import InsuranceReservePolicyInput
from app.services.insurance_reserve import (
    InsuranceReservePolicyService,
    compute_required_minimum_reserve,
)
from app.services.wallet import (
    InsufficientInsuranceReserveError,
    WalletService,
)


def _headers(account) -> dict:
    return {"Authorization": f"Bearer {create_access_token(account.id, account.role.value)}"}


async def _enable_policy(
    db_session, actor, *, percentage: str, enabled: bool = True
) -> InsuranceReservePolicy:
    repo = InsuranceReservePolicyRepository(db_session)
    service = InsuranceReservePolicyService(repo)
    draft = await service.create(
        actor, {"enabled": enabled, "minimum_reserve_percentage": Decimal(percentage)}
    )
    return await service.activate(draft.id)


# ---------------------------------------------------------------------------
# Formula
# ---------------------------------------------------------------------------


def test_required_minimum_formula():
    assert compute_required_minimum_reserve(Decimal("1000"), Decimal("10")) == Decimal(
        "100.00000000"
    )
    assert compute_required_minimum_reserve(Decimal("0"), Decimal("10")) == Decimal("0E-8") or (
        compute_required_minimum_reserve(Decimal("0"), Decimal("10")) == Decimal("0")
    )
    assert compute_required_minimum_reserve(Decimal("333"), Decimal("0")) == Decimal("0E-8") or (
        compute_required_minimum_reserve(Decimal("333"), Decimal("0")) == Decimal("0")
    )


# ---------------------------------------------------------------------------
# Policy CRUD / validation (API + schema level)
# ---------------------------------------------------------------------------


async def test_owner_can_create_and_activate_policy(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    created = await client.post(
        "/api/v1/owner/insurance-reserve-policies",
        json={"enabled": True, "minimum_reserve_percentage": "10.00"},
        headers=_headers(owner),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "draft"
    assert body["minimum_reserve_percentage"] == "10.00"

    activated = await client.post(
        f"/api/v1/owner/insurance-reserve-policies/{body['id']}/activate", headers=_headers(owner)
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    current = await client.get("/api/v1/owner/insurance-reserve-policy", headers=_headers(owner))
    assert current.status_code == 200
    assert current.json()["id"] == body["id"]
    assert current.json()["version"] == body["version"]


async def test_policy_update_creates_new_version_and_retires_old(client, db_session, make_account):
    owner = await make_account(role=UserRole.OWNER)
    first = await _enable_policy(db_session, owner, percentage="10.00")
    second = await _enable_policy(db_session, owner, percentage="15.00")
    assert second.version == first.version + 1
    await db_session.refresh(first)
    assert first.status == "retired"
    assert second.status == "active"


@pytest.mark.parametrize("value", ["0", "0.00", "100", "100.00"])
async def test_boundary_percentages_are_accepted(client, make_account, value):
    owner = await make_account(role=UserRole.OWNER)
    response = await client.post(
        "/api/v1/owner/insurance-reserve-policies",
        json={"enabled": True, "minimum_reserve_percentage": value},
        headers=_headers(owner),
    )
    assert response.status_code == 201


@pytest.mark.parametrize("value", ["-0.01", "-10", "100.01", "150"])
async def test_out_of_range_percentages_are_rejected(client, make_account, value):
    owner = await make_account(role=UserRole.OWNER)
    response = await client.post(
        "/api/v1/owner/insurance-reserve-policies",
        json={"enabled": True, "minimum_reserve_percentage": value},
        headers=_headers(owner),
    )
    assert response.status_code == 422


def test_float_input_is_rejected_by_schema():
    with pytest.raises(ValidationError, match="float"):
        InsuranceReservePolicyInput(enabled=True, minimum_reserve_percentage=10.5)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_input_is_rejected_by_schema(value):
    with pytest.raises(ValidationError):
        InsuranceReservePolicyInput(enabled=True, minimum_reserve_percentage=value)


def test_precision_is_normalized_to_two_decimal_places():
    parsed = InsuranceReservePolicyInput(enabled=True, minimum_reserve_percentage="10.1")
    assert parsed.minimum_reserve_percentage == Decimal("10.10")


async def test_non_owner_cannot_read_or_change_policy(client, make_account):
    user = await make_account(role=UserRole.USER)
    merchant = await make_account(role=UserRole.MERCHANT)
    for account in (user, merchant):
        assert (
            await client.get("/api/v1/owner/insurance-reserve-policy", headers=_headers(account))
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/owner/insurance-reserve-policies",
                json={"enabled": True, "minimum_reserve_percentage": "10.00"},
                headers=_headers(account),
            )
        ).status_code == 403


async def test_policy_create_and_activate_are_audited(client, db_session, make_account):
    owner = await make_account(role=UserRole.OWNER)
    created = await client.post(
        "/api/v1/owner/insurance-reserve-policies",
        json={"enabled": True, "minimum_reserve_percentage": "12.00"},
        headers=_headers(owner),
    )
    policy_id = created.json()["id"]
    await client.post(
        f"/api/v1/owner/insurance-reserve-policies/{policy_id}/activate", headers=_headers(owner)
    )
    actions = set(
        (
            await db_session.execute(select(AuditLog.action).where(AuditLog.entity_id == policy_id))
        ).scalars()
    )
    assert {"insurance_reserve_policy.created", "insurance_reserve_policy.activated"} <= actions


# ---------------------------------------------------------------------------
# Enforcement: high-water-mark basis, boundary, denial, rollback, audit
# ---------------------------------------------------------------------------


async def test_default_seeded_policy_is_disabled_and_changes_nothing(
    client, db_session, make_account, make_wallet
):
    """Safe default: with no Owner action taken, a large insurance decrease
    still succeeds exactly as it did before this feature existed."""
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


async def test_positive_adjustment_raises_basis_high_water_mark(
    client, db_session, make_account, make_wallet
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, insurance=Decimal("0"))
    assert wallet.insurance_reserve_basis == Decimal("0")

    await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "1000", "description": "top up", "idempotency_key": "basis-up-1"},
        headers=_headers(owner),
    )
    await db_session.refresh(wallet)
    assert wallet.insurance_reserve_basis == Decimal("1000.00000000")

    # A later top-up that still leaves the balance below the historical
    # high-water mark must not lower the basis.
    await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "-900", "description": "drawdown", "idempotency_key": "basis-up-2"},
        headers=_headers(owner),
    )
    await db_session.refresh(wallet)
    assert wallet.insurance_reserve_basis == Decimal("1000.00000000")
    assert wallet.insurance_balance == Decimal("100.00000000")

    await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "50", "description": "partial top up", "idempotency_key": "basis-up-3"},
        headers=_headers(owner),
    )
    await db_session.refresh(wallet)
    assert wallet.insurance_reserve_basis == Decimal("1000.00000000"), (
        "150 is still below the 1000 high-water mark - basis must not move"
    )


async def test_decrease_exactly_at_reserve_is_allowed(
    client, db_session, make_account, make_wallet
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, insurance=Decimal("1000"))
    wallet.insurance_reserve_basis = Decimal("1000")
    await db_session.flush()
    await _enable_policy(db_session, owner, percentage="10.00")

    # Required minimum = 100. Leaving exactly 100 must be allowed (rule is
    # strictly "<", not "<=").
    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "-900", "description": "to the edge", "idempotency_key": "edge-1"},
        headers=_headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["insurance_balance"] == "100.00000000"


async def test_decrease_below_reserve_is_denied_with_no_side_effects(
    client, db_session, make_account, make_wallet
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, insurance=Decimal("1000"))
    wallet.insurance_reserve_basis = Decimal("1000")
    await db_session.flush()
    await _enable_policy(db_session, owner, percentage="10.00")

    response = await client.post(
        f"/owner/accounts/{user.id}/wallet/insurance",
        json={"amount": "-901", "description": "over the edge", "idempotency_key": "deny-1"},
        headers=_headers(owner),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "INSUFFICIENT_INSURANCE_RESERVE"

    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("1000.00000000"), "balance must be untouched"
    assert wallet.insurance_reserve_basis == Decimal("1000.00000000")

    entries = (
        (
            await db_session.execute(
                select(LedgerEntry).where(LedgerEntry.idempotency_key == "deny-1")
            )
        )
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


async def test_decrease_that_stays_above_reserve_succeeds(
    client, db_session, make_account, make_wallet
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, insurance=Decimal("1000"))
    wallet.insurance_reserve_basis = Decimal("1000")
    await db_session.flush()
    await _enable_policy(db_session, owner, percentage="10.00")

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
    wallet = await make_wallet(user, insurance=Decimal("1000"))
    wallet.insurance_reserve_basis = Decimal("1000")
    await db_session.flush()
    await _enable_policy(db_session, owner, percentage="10.00")

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


async def test_get_insurance_reserve_view_reports_real_numbers(
    client, db_session, make_account, make_wallet
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, insurance=Decimal("1000"))
    wallet.insurance_reserve_basis = Decimal("1000")
    await db_session.flush()
    await db_session.refresh(wallet)
    policy = await _enable_policy(db_session, owner, percentage="10.00")

    response = await client.get(
        f"/owner/accounts/{user.id}/wallet/insurance-reserve", headers=_headers(owner)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["insurance_balance"] == "1000.00000000"
    assert body["insurance_reserve_basis"] == "1000.00000000"
    assert body["minimum_reserve_percentage"] == "10.00"
    assert body["required_minimum_reserve"] == "100.00000000"
    assert body["available_above_reserve"] == "900.00000000"
    assert body["policy_version"] == policy.version
    assert body["policy_enabled"] is True


# ---------------------------------------------------------------------------
# Concurrency: two racing decreases cannot together breach the reserve
# ---------------------------------------------------------------------------


async def test_concurrent_decreases_cannot_jointly_breach_the_reserve():
    """Wallet: insurance=1000, basis=1000, reserve=10% -> floor=100.
    Two concurrent -500 decreases would jointly leave -0 (breach); the row
    lock must serialize them so only one succeeds and the other is denied,
    never both applied."""
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
            insurance_reserve_basis=Decimal("1000"),
        )
        await wallet_repo.create(wallet)

        policy_repo = InsuranceReservePolicyRepository(setup_session)
        policy_service = InsuranceReservePolicyService(policy_repo)
        draft = await policy_service.create(
            owner, {"enabled": True, "minimum_reserve_percentage": Decimal("10.00")}
        )
        await policy_service.activate(draft.id)

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
                "the reserve floor must never be breached even under concurrency"
            )
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            # Restore the platform-wide policy to its safe, disabled default
            # so no later test in this same run inherits an enabled reserve.
            policy_repo = InsuranceReservePolicyRepository(cleanup_session)
            policy_service = InsuranceReservePolicyService(policy_repo)
            owner_stub = Account(
                id=owner_id, username="x", password_hash="x", role=UserRole.OWNER, full_name="x"
            )
            draft = await policy_service.create(
                owner_stub, {"enabled": False, "minimum_reserve_percentage": Decimal("0")}
            )
            await policy_service.activate(draft.id)
            await cleanup_session.execute(
                update(InsuranceReservePolicy)
                .where(InsuranceReservePolicy.created_by_account_id.in_([user_id, owner_id]))
                .values(created_by_account_id=None)
            )
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
    wallet.insurance_reserve_basis = Decimal("42")
    await db_session.flush()
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )
    deal_id = uuid.uuid4()
    await service.freeze_for_deal(account_id=user.id, amount=Decimal("50"), deal_id=deal_id)
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("42.00000000")
    assert wallet.insurance_reserve_basis == Decimal("42.00000000")

    await service.release_for_deal(user_account_id=user.id, amount=Decimal("50"), deal_id=deal_id)
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("42.00000000")
    assert wallet.insurance_reserve_basis == Decimal("42.00000000")


async def test_user_withdrawal_hold_release_pay_never_touch_insurance(
    db_session, make_account, make_wallet
):
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, available=Decimal("100"), insurance=Decimal("17"))
    wallet.insurance_reserve_basis = Decimal("17")
    await db_session.flush()
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
    assert wallet.insurance_reserve_basis == Decimal("17.00000000")


async def test_deposit_credit_never_touches_insurance(db_session, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, insurance=Decimal("5"))
    wallet.insurance_reserve_basis = Decimal("5")
    await db_session.flush()
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )
    await service.credit_deposit(account_id=user.id, amount=Decimal("30"), deposit_id=uuid.uuid4())
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("5.00000000")
    assert wallet.insurance_reserve_basis == Decimal("5.00000000")


async def test_settle_deal_never_touches_user_insurance(
    db_session, make_account, make_wallet, make_merchant_wallet
):
    user = await make_account(role=UserRole.USER)
    merchant = await make_account(role=UserRole.MERCHANT)
    wallet = await make_wallet(user, available=Decimal("200"), insurance=Decimal("9"))
    wallet.insurance_reserve_basis = Decimal("9")
    await make_merchant_wallet(merchant)
    await db_session.flush()
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
    assert wallet.insurance_reserve_basis == Decimal("9.00000000")


async def test_team_lead_profit_credit_never_touches_insurance(
    db_session, make_account, make_wallet
):
    team_lead = await make_account(role=UserRole.TEAM_LEAD)
    wallet = await make_wallet(team_lead, insurance=Decimal("6"))
    wallet.insurance_reserve_basis = Decimal("6")
    await db_session.flush()
    service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), AccountRepository(db_session)
    )
    await service.credit_team_lead_profit(
        team_lead_account_id=team_lead.id, amount=Decimal("1.5"), deal_id=uuid.uuid4()
    )
    await db_session.refresh(wallet)
    assert wallet.insurance_balance == Decimal("6.00000000")
    assert wallet.insurance_reserve_basis == Decimal("6.00000000")


async def test_manual_adjust_and_allocate_use_available_bucket_never_insurance(
    db_session, make_account, make_wallet
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, insurance=Decimal("8"))
    wallet.insurance_reserve_basis = Decimal("8")
    await db_session.flush()
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
    assert wallet.insurance_reserve_basis == Decimal("8.00000000")
