"""Dynamic per-user payout destination security: each beneficiary's
withdrawal auto-registers its own beneficiary-scoped PayoutDestination
(app/services/payout.py::ControlledPayoutService._ensure_destination), and
_live_gate re-checks the exact (beneficiary, address) pair on every call -
not just an aggregate "some destination exists" count. These tests cover
what's new about that model: isolation between beneficiaries, tamper
resistance of the beneficiary binding, Owner visibility of the real address
before approval, and that the exact user-typed address is what reaches the
Bybit payload. Basic tamper detection, dual-approval, and TRC20
length/checksum validation at withdrawal creation are covered elsewhere
(test_payout.py, test_withdrawals.py, test_live_payout_execution.py) and are
not duplicated here."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.core.config import settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.payout import PayoutSimulationOutcome
from app.models.risk import TreasurySnapshotRecord
from app.repositories.payout import PayoutRepository
from app.repositories.payout_security import PayoutSecurityRepository
from app.services.payout import PayoutSafetyError
from app.services.payout_live.bybit import BybitLivePayoutProvider
from app.services.payout_runtime import build_controlled_payout_service

VALID_TRC20_A = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
VALID_TRC20_B = "TJCx4A1XzNvy32sqbmi86xcURjRi1Etver"


def _headers(account):
    return {"Authorization": f"Bearer {create_access_token(account.id, role=account.role)}"}


async def _enable_simulation(db_session, monkeypatch):
    monkeypatch.setattr(settings, "PAYOUT_ENABLED", True)
    monkeypatch.setattr(settings, "PAYOUT_PROVIDER_MODE", "simulated")
    monkeypatch.setattr(settings, "PAYOUT_SIMULATION_ENABLED", True)
    policy = await PayoutRepository(db_session).active_policy()
    policy.payouts_enabled = True
    db_session.add(
        TreasurySnapshotRecord(
            external_observed_at=datetime.now(UTC),
            provider_status="connected",
            external_bybit_usdt=Decimal("100000"),
            external_bybit_usdc=Decimal("0"),
            internal_user_liability_usdt=Decimal("0"),
            merchant_liability_usdt=Decimal("0"),
            frozen_usdt=Decimal("0"),
            pending_withdrawal_usdt=Decimal("0"),
            open_deal_exposure_usdt=Decimal("0"),
            owner_profit_usdt=Decimal("0"),
            required_reserve_usdt=Decimal("0"),
            reserve_surplus_usdt=Decimal("100000"),
            reserve_deficit_usdt=Decimal("0"),
            coverage_ratio_bps=None,
            risk_status="healthy",
            policy_version=1,
        )
    )
    await db_session.flush()


async def _withdrawal(client, merchant, destination, amount="25"):
    response = await client.post(
        "/merchant/withdrawals",
        json={
            "amount": amount,
            "destination_type": "usdt_trc20_address",
            "destination": destination,
        },
        headers=_headers(merchant),
    )
    assert response.status_code == 201
    return response.json()


async def _intent_for(client, owner, withdrawal_id):
    response = await client.get("/api/v1/owner/payouts", headers=_headers(owner))
    assert response.status_code == 200
    for item in response.json()["items"]:
        if item["withdrawal_id"] == withdrawal_id:
            return item
    raise AssertionError(f"no payout intent found for withdrawal {withdrawal_id}")


async def test_dynamic_destinations_are_scoped_per_beneficiary(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    """Two different merchants withdrawing to two different addresses must
    each get their own beneficiary-scoped PayoutDestination row - this is
    the core of the "dynamic per-user destination" model confirmed by the
    Owner, replacing a single global Owner-curated allowlist."""
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant_a, available=Decimal("100"))
    await make_merchant_wallet(merchant_b, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)

    await _withdrawal(client, merchant_a, VALID_TRC20_A, "10")
    await _withdrawal(client, merchant_b, VALID_TRC20_B, "10")

    security = PayoutSecurityRepository(db_session)
    destinations_a = await security.destinations_for_beneficiary(merchant_a.id)
    destinations_b = await security.destinations_for_beneficiary(merchant_b.id)
    assert len(destinations_a) == 1
    assert len(destinations_b) == 1
    assert destinations_a[0].address == VALID_TRC20_A
    assert destinations_b[0].address == VALID_TRC20_B
    assert destinations_a[0].id != destinations_b[0].id


async def test_repeat_withdrawal_to_same_address_reuses_destination(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)

    await _withdrawal(client, merchant, VALID_TRC20_A, "10")
    await _withdrawal(client, merchant, VALID_TRC20_A, "5")

    security = PayoutSecurityRepository(db_session)
    destinations = await security.destinations_for_beneficiary(merchant.id)
    assert len(destinations) == 1


async def test_disabling_one_beneficiarys_destination_does_not_block_another(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    """IDOR-style isolation: the composite (beneficiary, fingerprint) unique
    index means Owner disabling merchant A's destination (e.g. suspected
    fraud) must have no effect on merchant B's unrelated, still-enabled
    destination - even if merchant B happens to use the exact same address."""
    merchant_a = await make_account(role=UserRole.MERCHANT)
    merchant_b = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant_a, available=Decimal("100"))
    await make_merchant_wallet(merchant_b, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)

    await _withdrawal(client, merchant_a, VALID_TRC20_A, "10")
    await _withdrawal(client, merchant_b, VALID_TRC20_A, "10")

    security = PayoutSecurityRepository(db_session)
    destination_a = (await security.destinations_for_beneficiary(merchant_a.id))[0]
    destination_b = (await security.destinations_for_beneficiary(merchant_b.id))[0]
    assert destination_a.id != destination_b.id, (
        "same address, different beneficiaries - must be two distinct rows"
    )

    destination_a.enabled = False
    await db_session.flush()

    fingerprint = destination_b.fingerprint
    still_usable = await security.destination_by_fingerprint(merchant_b.id, fingerprint)
    assert still_usable is not None
    assert still_usable.enabled is True


async def test_beneficiary_account_id_tampering_is_blocked(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    """intent_hash() binds `beneficiary` - swapping which account a payout
    is attributed to after creation (e.g. to route it through a different
    beneficiary's approved destination) must be caught as tampering, exactly
    like amount/destination/network tampering already is."""
    merchant = await make_account(role=UserRole.MERCHANT)
    other_merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)

    withdrawal = await _withdrawal(client, merchant, VALID_TRC20_A, "10")
    intent_data = await _intent_for(client, owner, withdrawal["id"])
    intent = await PayoutRepository(db_session).get(intent_data["id"], lock=True)
    assert intent is not None
    intent.beneficiary_account_id = other_merchant.id

    with pytest.raises(PayoutSafetyError, match="PAYOUT_INTENT_CHANGED"):
        await build_controlled_payout_service(db_session).cancel(intent.id, owner)


async def test_owner_sees_full_destination_before_approving(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    """Owner detail view must show the real destination address, network,
    asset, amount, and beneficiary - not just a masked value - before any
    approval decision is made."""
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)

    withdrawal = await _withdrawal(client, merchant, VALID_TRC20_A, "10")
    intent_data = await _intent_for(client, owner, withdrawal["id"])
    assert intent_data["status"] == "risk_review"
    assert intent_data["approval_count"] == 0

    detail = await client.get(
        f"/api/v1/owner/payouts/{intent_data['id']}", headers=_headers(owner)
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["destination"] == VALID_TRC20_A
    assert body["network"] == "TRC20"
    assert body["asset"] == "USDT"
    assert body["beneficiary_account_id"] == str(merchant.id)
    assert Decimal(body["amount"]) == Decimal("10")


async def test_owner_list_view_does_not_leak_full_destination(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    """The list endpoint (used for dashboards/overviews) stays masked - only
    the single-intent detail view exposes the full address."""
    merchant = await make_account(role=UserRole.MERCHANT)
    owner = await make_account(role=UserRole.OWNER)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    await _enable_simulation(db_session, monkeypatch)

    await _withdrawal(client, merchant, VALID_TRC20_A, "10")
    listing = await client.get("/api/v1/owner/payouts", headers=_headers(owner))
    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert item["destination"] is None
    assert item["masked_destination"] != VALID_TRC20_A


async def test_live_gate_rejects_non_trc20_network(
    client, db_session, make_account, make_merchant_wallet, monkeypatch
):
    """create_for_withdrawal only ever produces a live-provider intent for
    network="TRC20" (a bybit_uid withdrawal falls back to provider_mode
    "disabled" even with PAYOUT_PROVIDER_MODE=live globally), so the only way
    to exercise _live_gate's own LIVE_NETWORK_NOT_SUPPORTED check is a
    defense-in-depth scenario: a live-mode TRC20 intent whose network gets
    swapped to BYBIT_UID before approval (e.g. a bug elsewhere in the
    approval pipeline), then legitimately approved twice under the new
    hash. Even then, _live_gate must independently refuse to queue it."""
    from app.services.payout import intent_hash

    merchant = await make_account(role=UserRole.MERCHANT)
    owner_a = await make_account(role=UserRole.OWNER)
    owner_b = await make_account(role=UserRole.OWNER)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    monkeypatch.setattr(settings, "PAYOUT_PROVIDER_MODE", "live")
    monkeypatch.setattr(settings, "PAYOUT_ENABLED", True)
    payout_repo = PayoutRepository(db_session)
    policy = await payout_repo.active_policy()
    policy.payouts_enabled = True
    policy.default_required_approvals = 2
    policy.high_value_required_approvals = 2
    from app.repositories.risk import RiskRepository

    risk_repo = RiskRepository(db_session)
    risk_policy = await risk_repo.active_policy()
    risk_policy.reserve_coverage_enabled = True
    risk_policy.minimum_external_reserve_enabled = True
    risk_policy.minimum_external_usdt_reserve = Decimal("0")
    db_session.add(
        TreasurySnapshotRecord(
            external_observed_at=datetime.now(UTC),
            provider_status="connected",
            external_bybit_usdt=Decimal("100000"),
            external_bybit_usdc=Decimal("0"),
            internal_user_liability_usdt=Decimal("0"),
            merchant_liability_usdt=Decimal("0"),
            frozen_usdt=Decimal("0"),
            pending_withdrawal_usdt=Decimal("0"),
            open_deal_exposure_usdt=Decimal("0"),
            owner_profit_usdt=Decimal("0"),
            required_reserve_usdt=Decimal("0"),
            reserve_surplus_usdt=Decimal("100000"),
            reserve_deficit_usdt=Decimal("0"),
            coverage_ratio_bps=None,
            risk_status="healthy",
            policy_version=risk_policy.version,
        )
    )
    await db_session.flush()

    withdrawal = await _withdrawal(client, merchant, VALID_TRC20_A, "10")
    intent_data = await _intent_for(client, owner_a, withdrawal["id"])
    assert intent_data["network"] == "TRC20"
    intent = await payout_repo.get(intent_data["id"], lock=True)
    assert intent is not None and intent.provider_mode == "live"
    intent.network = "BYBIT_UID"
    intent.intent_hash = intent_hash(intent)
    await db_session.flush()

    service = build_controlled_payout_service(db_session)
    await service.approve(intent.id, owner_a)
    await service.approve(intent.id, owner_b)
    await db_session.refresh(intent)
    assert intent.status == "approved"

    with pytest.raises(PayoutSafetyError, match="LIVE_NETWORK_NOT_SUPPORTED"):
        await service.queue(intent.id, owner_b, outcome=PayoutSimulationOutcome.SUCCEEDED)


async def test_live_payload_carries_exact_user_typed_destination(monkeypatch):
    """The write payload's `address` field must be exactly the user-typed
    destination on the intent - never a substituted, normalized, or
    Owner-side value."""
    from app.enums.payout import PayoutProviderResult
    from app.models.payout import PayoutIntent
    from app.services.exchange_private.models import ExchangeWithdrawalNetwork
    from app.services.payout_live.bybit import BybitWritePayoutClient

    monkeypatch.setattr(
        "app.services.exchange_private.runtime.get_bybit_private_client",
        lambda: _FakeReadOnly(
            [
                ExchangeWithdrawalNetwork(
                    provider="bybit",
                    asset="USDT",
                    chain="TRX",
                    chain_type="TRC20",
                    fixed_fee=Decimal("1"),
                    percentage_fee=Decimal("0"),
                    minimum_amount=Decimal("10"),
                    maximum_amount=Decimal("100000"),
                    decimal_places=6,
                    withdraw_enabled=True,
                    received_at=datetime.now(UTC),
                )
            ]
        ),
    )

    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"retCode": 0, "retMsg": "x", "result": {"id": "BYBIT-WD-99"}}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    write_client = BybitWritePayoutClient(
        base_url="https://api.bybit.test",
        api_key="dummy-write-key",
        api_secret="dummy-write-secret",
        recv_window_ms=5000,
        timeout_seconds=1,
        query_max_retries=2,
        client=http,
        clock_ms=lambda: 1788048000000,
    )
    write_client._clock_synchronized = True
    provider = BybitLivePayoutProvider(write_client=write_client)
    intent = PayoutIntent(
        id=uuid.uuid4(),
        asset="USDT",
        network="TRC20",
        destination=VALID_TRC20_B,
        amount=Decimal("25"),
        fee_amount=Decimal("0"),
        external_reference=None,
    )
    result = await provider.execute(intent)
    assert result.status == PayoutProviderResult.SUCCEEDED
    assert captured["body"]["address"] == VALID_TRC20_B


class _FakeReadOnly:
    def __init__(self, networks):
        self._networks = networks

    async def get_withdrawal_networks(self, asset):
        return self._networks
