from decimal import Decimal

from app.core.config import settings as app_settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.deal import DealStatus


def _auth_headers(account) -> dict:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _notifications_for(client, account, type_: str) -> list[dict]:
    response = await client.get(
        "/notifications", params={"type": type_}, headers=_auth_headers(account)
    )
    assert response.status_code == 200
    return response.json()


async def test_opening_appeal_notifies_counterparty(
    client, make_account, make_wallet, make_merchant_wallet, make_deal
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, frozen=Decimal("20"))
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant)
    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("20")
    )

    response = await client.post(
        f"/appeals/deals/{deal.id}/appeal",
        json={"reason_code": "payment_not_received", "message": "Payment never arrived"},
        headers=_auth_headers(user),
    )
    assert response.status_code == 201

    merchant_notifications = await _notifications_for(client, merchant, "APPEAL_OPENED")
    assert len(merchant_notifications) == 1
    assert merchant_notifications[0]["message_key"] == "appeal.opened"
    assert merchant_notifications[0]["message_params"] == {"reference": deal.public_id}

    user_notifications = await _notifications_for(client, user, "APPEAL_OPENED")
    assert len(user_notifications) == 0


async def test_resolving_appeal_notifies_both_parties(
    client, make_account, make_wallet, make_merchant_wallet, make_deal
):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, frozen=Decimal("20"))
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant)
    owner = await make_account(role=UserRole.OWNER)
    deal = await make_deal(
        merchant, status=DealStatus.ACCEPTED, user=user, amount_usdt=Decimal("20")
    )

    open_resp = await client.post(
        f"/appeals/deals/{deal.id}/appeal",
        json={"reason_code": "payment_not_received", "message": "Payment never arrived"},
        headers=_auth_headers(user),
    )
    appeal_id = open_resp.json()["id"]

    resolve_resp = await client.post(
        f"/owner/appeals/{appeal_id}/resolve",
        json={"resolution": "release_to_user", "owner_note": "Verified proof"},
        headers=_auth_headers(owner),
    )
    assert resolve_resp.status_code == 200

    user_notifications = await _notifications_for(client, user, "APPEAL_RESOLVED")
    merchant_notifications = await _notifications_for(client, merchant, "APPEAL_RESOLVED")
    assert user_notifications[0]["message_key"] == "appeal.resolved"
    assert merchant_notifications[0]["message_key"] == "appeal.resolved"


async def test_credited_deposit_notifies_user(client, make_account, make_wallet, make_deposit):
    user = await make_account(role=UserRole.USER)
    await make_wallet(user)
    owner = await make_account(role=UserRole.OWNER)
    deposit = await make_deposit(user, expected_amount=Decimal("60"), required_confirmations=1)

    response = await client.post(
        f"/owner/dev/deposits/{deposit.id}/simulate",
        json={
            "tx_hash": "tx-notify-1",
            "amount": "60",
            "confirmations": 1,
            "network": "TRC20",
            "asset": "USDT",
            "destination_address": app_settings.USDT_TRC20_DEPOSIT_ADDRESS,
        },
        headers=_auth_headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "credited"

    notifications = await _notifications_for(client, user, "DEPOSIT_CONFIRMED")
    assert notifications[0]["message_key"] == "deposit.credited"
    assert notifications[0]["message_params"]["reference"] == deposit.public_id
    assert notifications[0]["message_params"]["currency"] == "USDT"
    assert isinstance(notifications[0]["message_params"]["amount"], str)
    assert Decimal(notifications[0]["message_params"]["amount"]) == Decimal("60")


async def test_withdrawal_status_change_notifies_merchant(
    client, make_account, make_merchant_wallet
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    owner = await make_account(role=UserRole.OWNER)

    create_resp = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": "25",
            "destination_type": "usdt_trc20_address",
            "destination": "T" * 34,
        },
        headers=_auth_headers(merchant),
    )
    withdrawal_id = create_resp.json()["id"]

    approve_resp = await client.post(
        f"/owner/withdrawals/{withdrawal_id}/approve", headers=_auth_headers(owner)
    )
    assert approve_resp.status_code == 200

    direct_paid_resp = await client.post(
        f"/owner/withdrawals/{withdrawal_id}/mark-paid", headers=_auth_headers(owner)
    )
    assert direct_paid_resp.status_code == 409
    assert direct_paid_resp.json()["detail"]["code"] == "CONTROLLED_PAYOUT_REQUIRED"

    notifications = await _notifications_for(client, merchant, "WITHDRAWAL_STATUS_CHANGED")
    # Approval is emitted, but direct paid finalization is blocked by the payout control plane.
    assert len(notifications) == 1
    assert notifications[0]["message_key"] == "withdrawal.approved"
