from decimal import Decimal

from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.wallet import LedgerEntryType
from app.repositories.audit import AuditRepository
from app.repositories.notification import NotificationRepository
from app.repositories.realtime import RealtimeOutboxRepository


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _create(client, user, amount: str = "20") -> dict:
    response = await client.post(
        "/withdrawals",
        json={
            "amount": amount,
            "destination_type": "usdt_trc20_address",
            "destination": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        },
        headers=_auth_headers(user),
    )
    assert response.status_code == 201
    return response.json()


async def test_user_creates_withdrawal(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))

    response = await client.post(
        "/withdrawals",
        json={
            "amount": "40",
            "destination_type": "usdt_trc20_address",
            "destination": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["amount"] == "40.00000000"
    assert body["public_id"].startswith("UWD-")


async def test_create_withdrawal_invalid_trc20_checksum_rejected(client, make_account, make_wallet):
    """Correct length (34 chars, starts with T) but a corrupted base58check
    checksum - must be rejected at creation time, before any approval."""
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))

    response = await client.post(
        "/withdrawals",
        json={
            "amount": "40",
            "destination_type": "usdt_trc20_address",
            "destination": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6x",
        },
        headers=_auth_headers(user),
    )
    assert response.status_code == 400
    assert "invalid TRC20 address checksum" in response.json()["detail"]


async def test_withdrawal_holds_funds_from_available_balance(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))

    await client.post(
        "/withdrawals",
        json={
            "amount": "40",
            "destination_type": "usdt_trc20_address",
            "destination": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        },
        headers=_auth_headers(user),
    )

    wallet_response = await client.get("/wallet", headers=_auth_headers(user))
    assert wallet_response.json()["available_balance"] == "60.00000000"
    assert wallet_response.json()["frozen_balance"] == "40.00000000"


async def test_withdrawal_rejects_insufficient_balance(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("10"))

    response = await client.post(
        "/withdrawals",
        json={
            "amount": "40",
            "destination_type": "usdt_trc20_address",
            "destination": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        },
        headers=_auth_headers(user),
    )

    assert response.status_code == 400


async def test_merchant_cannot_create_user_withdrawal(client, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/withdrawals",
        json={
            "amount": "40",
            "destination_type": "usdt_trc20_address",
            "destination": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        },
        headers=_auth_headers(merchant),
    )

    assert response.status_code == 403


async def test_user_cannot_see_another_users_withdrawal(client, make_account, make_wallet):
    user_a = await make_account(role=UserRole.USER)
    user_b = await make_account(role=UserRole.USER)
    await make_wallet(user_a, available=Decimal("100"))

    create = await client.post(
        "/withdrawals",
        json={
            "amount": "10",
            "destination_type": "usdt_trc20_address",
            "destination": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        },
        headers=_auth_headers(user_a),
    )
    withdrawal_id = create.json()["id"]

    response = await client.get(
        f"/withdrawals/{withdrawal_id}", headers=_auth_headers(user_b)
    )

    assert response.status_code == 404


async def test_user_cancels_pending_withdrawal_and_funds_released(
    client, make_account, make_wallet
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    create = await client.post(
        "/withdrawals",
        json={
            "amount": "30",
            "destination_type": "usdt_trc20_address",
            "destination": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        },
        headers=_auth_headers(user),
    )
    withdrawal_id = create.json()["id"]

    cancel = await client.post(
        f"/withdrawals/{withdrawal_id}/cancel", headers=_auth_headers(user)
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    wallet_response = await client.get("/wallet", headers=_auth_headers(user))
    assert wallet_response.json()["available_balance"] == "100.00000000"
    assert wallet_response.json()["frozen_balance"] == "0.00000000"


async def test_owner_approves_and_rejects_user_withdrawal(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    create = await client.post(
        "/withdrawals",
        json={
            "amount": "20",
            "destination_type": "usdt_trc20_address",
            "destination": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        },
        headers=_auth_headers(user),
    )
    withdrawal_id = create.json()["id"]

    approve = await client.post(
        f"/owner/user-withdrawals/{withdrawal_id}/approve", headers=_auth_headers(owner)
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    # Can't reject once approved.
    reject_after_approve = await client.post(
        f"/owner/user-withdrawals/{withdrawal_id}/reject", headers=_auth_headers(owner)
    )
    assert reject_after_approve.status_code == 400


async def test_owner_rejects_user_withdrawal_and_releases_funds(
    client, make_account, make_wallet
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    create = await client.post(
        "/withdrawals",
        json={
            "amount": "20",
            "destination_type": "usdt_trc20_address",
            "destination": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        },
        headers=_auth_headers(user),
    )
    withdrawal_id = create.json()["id"]

    reject = await client.post(
        f"/owner/user-withdrawals/{withdrawal_id}/reject", headers=_auth_headers(owner)
    )
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"

    wallet_response = await client.get("/wallet", headers=_auth_headers(user))
    assert wallet_response.json()["available_balance"] == "100.00000000"


async def test_owner_marks_approved_withdrawal_paid(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    withdrawal = await _create(client, user, "20")
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/approve", headers=_auth_headers(owner)
    )

    response = await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "paid"
    assert response.json()["paid_at"] is not None


async def test_paid_withdrawal_deducts_frozen_without_returning_to_available(
    client, make_account, make_wallet
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    withdrawal = await _create(client, user, "20")
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/approve", headers=_auth_headers(owner)
    )

    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )

    wallet_response = await client.get("/wallet", headers=_auth_headers(user))
    body = wallet_response.json()
    # available stayed at 80 (already debited at creation) - the 20 that
    # was frozen is now gone entirely, not returned to available.
    assert body["available_balance"] == "80.00000000"
    assert body["frozen_balance"] == "0.00000000"


async def test_paid_withdrawal_cannot_be_paid_again(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    withdrawal = await _create(client, user, "20")
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/approve", headers=_auth_headers(owner)
    )
    first = await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )
    assert first.status_code == 200

    second = await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )

    # Idempotent re-call: same terminal state, not an error, and critically
    # no second ledger entry / balance change (verified separately below).
    assert second.status_code == 200
    assert second.json()["status"] == "paid"

    wallet_response = await client.get("/wallet", headers=_auth_headers(user))
    assert wallet_response.json()["available_balance"] == "80.00000000"


async def test_rejected_withdrawal_cannot_be_paid(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    withdrawal = await _create(client, user, "20")
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/reject", headers=_auth_headers(owner)
    )

    response = await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )

    assert response.status_code == 400


async def test_cancelled_withdrawal_cannot_be_paid(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    withdrawal = await _create(client, user, "20")
    await client.post(f"/withdrawals/{withdrawal['id']}/cancel", headers=_auth_headers(user))

    response = await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )

    assert response.status_code == 400


async def test_pending_withdrawal_cannot_be_paid_directly(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    withdrawal = await _create(client, user, "20")

    response = await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )

    assert response.status_code == 400


async def test_paid_withdrawal_creates_exactly_one_ledger_entry(
    client, make_account, make_wallet, db_session
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    withdrawal = await _create(client, user, "20")
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/approve", headers=_auth_headers(owner)
    )
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )
    # Retry the same idempotent action once more.
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )

    ledger_response = await client.get("/wallet/ledger", headers=_auth_headers(user))
    entries = ledger_response.json()["items"]
    paid_entries = [e for e in entries if e["type"] == LedgerEntryType.WITHDRAWAL_PAID.value]
    assert len(paid_entries) == 1


async def test_owner_lifecycle_actions_are_audited(client, make_account, make_wallet, db_session):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    withdrawal = await _create(client, user, "20")
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/approve", headers=_auth_headers(owner)
    )
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )

    audit_repo = AuditRepository(db_session)
    logs = await audit_repo.list_logs(entity_type="user_withdrawal", limit=50)
    actions = {log.action for log in logs if str(log.entity_id) == withdrawal["id"]}
    assert "user_withdrawal.approve" in actions
    assert "user_withdrawal.mark_paid" in actions
    assert all(log.actor_account_id == owner.id for log in logs if str(log.entity_id) == withdrawal["id"])


async def test_paid_status_change_emits_notification(client, make_account, make_wallet, db_session):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    withdrawal = await _create(client, user, "20")
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/approve", headers=_auth_headers(owner)
    )
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )

    notification_repo = NotificationRepository(db_session)
    notifications = await notification_repo.list_for_account(user.id, limit=50, offset=0)
    assert any(
        n.payload.get("withdrawal_id") == withdrawal["id"] and n.payload.get("status") == "paid"
        for n in notifications
    )


async def test_paid_status_change_emits_realtime_event(
    client, make_account, make_wallet, db_session
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    withdrawal = await _create(client, user, "20")
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/approve", headers=_auth_headers(owner)
    )
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )

    realtime_repo = RealtimeOutboxRepository(db_session)
    pending = await realtime_repo.pending(limit=100)
    assert any(
        str(entry.entity_id) == withdrawal["id"] and entry.data.get("status") == "paid"
        for entry in pending
    )


async def test_owner_sees_paid_withdrawal(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    withdrawal = await _create(client, user, "20")
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/approve", headers=_auth_headers(owner)
    )
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )

    response = await client.get(
        f"/owner/user-withdrawals/{withdrawal['id']}", headers=_auth_headers(owner)
    )
    assert response.json()["status"] == "paid"


async def test_user_sees_paid_withdrawal(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    withdrawal = await _create(client, user, "20")
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/approve", headers=_auth_headers(owner)
    )
    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/mark-paid", headers=_auth_headers(owner)
    )

    response = await client.get(
        f"/withdrawals/{withdrawal['id']}", headers=_auth_headers(user)
    )
    assert response.json()["status"] == "paid"


async def test_balance_invariant_holds_after_reject(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)
    withdrawal = await _create(client, user, "35")

    await client.post(
        f"/owner/user-withdrawals/{withdrawal['id']}/reject", headers=_auth_headers(owner)
    )

    wallet_response = await client.get("/wallet", headers=_auth_headers(user))
    body = wallet_response.json()
    assert body["available_balance"] == "100.00000000"
    assert body["frozen_balance"] == "0.00000000"


async def test_balance_invariant_holds_after_cancel(client, make_account, make_wallet):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("100"))
    withdrawal = await _create(client, user, "35")

    await client.post(f"/withdrawals/{withdrawal['id']}/cancel", headers=_auth_headers(user))

    wallet_response = await client.get("/wallet", headers=_auth_headers(user))
    body = wallet_response.json()
    assert body["available_balance"] == "100.00000000"
    assert body["frozen_balance"] == "0.00000000"


async def test_owner_lists_all_user_withdrawals(client, make_account, make_wallet):
    user_a = await make_account(role=UserRole.USER)
    user_b = await make_account(role=UserRole.USER)
    await make_wallet(user_a, available=Decimal("50"))
    await make_wallet(user_b, available=Decimal("50"))
    owner = await make_account(role=UserRole.OWNER)

    await client.post(
        "/withdrawals",
        json={
            "amount": "10",
            "destination_type": "usdt_trc20_address",
            "destination": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        },
        headers=_auth_headers(user_a),
    )
    await client.post(
        "/withdrawals",
        json={
            "amount": "15",
            "destination_type": "usdt_trc20_address",
            "destination": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        },
        headers=_auth_headers(user_b),
    )

    response = await client.get("/owner/user-withdrawals", headers=_auth_headers(owner))

    assert response.status_code == 200
    assert response.json()["total"] == 2
