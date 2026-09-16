"""Live Bybit payout execution tests - transport, retCode classification,
provider integration, and the ControlledPayoutService live-mode gates. The
existing simulated-mode state machine (approval, tamper detection, dual
control, kill switches) is already covered by test_payout.py /
test_payout_concurrency.py and is not duplicated here; these tests focus on
what is new: the write transport and its wiring."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.payout import PayoutProviderResult, PayoutSimulationOutcome, PayoutStatus
from app.models.payout import PayoutIntent
from app.models.risk import TreasurySnapshotRecord
from app.models.withdrawal import MerchantWithdrawal
from app.repositories.account import AccountRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.payout import PayoutRepository
from app.repositories.payout_security import PayoutSecurityRepository
from app.repositories.risk import RiskRepository
from app.repositories.wallet import WalletRepository
from app.repositories.withdrawal import WithdrawalRepository
from app.services.exchange_private.models import ExchangeWithdrawalNetwork
from app.services.payout import ControlledPayoutService, PayoutSafetyError
from app.services.payout_live.bybit import (
    BybitLivePayoutProvider,
    BybitWithdrawalDryRun,
    BybitWritePayoutClient,
    LivePayoutDuplicateRequest,
    LivePayoutPermanentFailure,
    LivePayoutTimeout,
)
from app.services.payout_live.readiness import LivePayoutReadinessService
from app.services.payout_provider import ProviderPayoutResult
from app.services.wallet import WalletService

VALID_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def _headers(account):
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


def _write_client(handler, *, query_max_retries=2) -> BybitWritePayoutClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    write_client = BybitWritePayoutClient(
        base_url="https://api.bybit.test",
        api_key="dummy-write-key",
        api_secret="dummy-write-secret",
        recv_window_ms=5000,
        timeout_seconds=1,
        query_max_retries=query_max_retries,
        client=http,
        clock_ms=lambda: 1788048000000,
    )
    # Clock sync hits a public, unauthenticated GET the handler never expects
    # to see in these targeted create/query tests - a fixed clock_ms is
    # already deterministic, so skip the sync round-trip entirely here.
    write_client._clock_synchronized = True
    return write_client


def _dry_run(*, request_id="11111111222233334444555555555555") -> BybitWithdrawalDryRun:
    return BybitWithdrawalDryRun(
        path="/v5/asset/withdraw/create",
        body='{"coin":"USDT"}',
        request_id=request_id,
        recipient_amount=Decimal("25"),
        network_fee=Decimal("1"),
        treasury_impact=Decimal("26"),
        metadata_observed_at=datetime(2026, 8, 30, tzinfo=UTC),
    )


def _bybit_response(ret_code: int, *, result: dict | None = None) -> httpx.Response:
    return httpx.Response(200, json={"retCode": ret_code, "retMsg": "x", "result": result or {}})


# ---------------------------------------------------------------------------
# BybitWritePayoutClient - transport, single-attempt create, retryable reads
# ---------------------------------------------------------------------------


async def test_create_withdrawal_success_returns_provider_withdraw_id():
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "POST"
        assert request.url.path == "/v5/asset/withdraw/create"
        assert request.content == b'{"coin":"USDT"}'
        assert request.headers["X-BAPI-API-KEY"] == "dummy-write-key"
        return _bybit_response(0, result={"id": "BYBIT-WD-1"})

    client = _write_client(handler)
    withdraw_id = await client.create_withdrawal(_dry_run())
    assert withdraw_id == "BYBIT-WD-1"
    assert len(seen) == 1
    await client.close()


async def test_create_withdrawal_duplicate_request_never_retried_as_new():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _bybit_response(131082)

    client = _write_client(handler)
    with pytest.raises(LivePayoutDuplicateRequest):
        await client.create_withdrawal(_dry_run())
    assert calls == 1
    await client.close()


@pytest.mark.parametrize(
    ("code", "reason"),
    [
        (131093, "ADDRESS_NOT_IN_APPROVED_LIST"),
        (110007, "INSUFFICIENT_AVAILABLE_BALANCE"),
        (131089, "SENSITIVE_OPERATION_LOCKOUT"),
    ],
)
async def test_create_withdrawal_permanent_failures_are_classified(code, reason):
    async def handler(request: httpx.Request) -> httpx.Response:
        return _bybit_response(code)

    client = _write_client(handler)
    with pytest.raises(LivePayoutPermanentFailure) as captured:
        await client.create_withdrawal(_dry_run())
    assert captured.value.code == code
    assert captured.value.reason == reason
    await client.close()


async def test_create_withdrawal_never_retries_on_timeout():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    client = _write_client(handler)
    with pytest.raises(LivePayoutTimeout):
        await client.create_withdrawal(_dry_run())
    assert calls == 1, "a POST that may have been accepted must never be resubmitted automatically"
    await client.close()


async def test_create_withdrawal_unrecognised_retcode_fails_closed_not_guessed():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _bybit_response(999999)

    client = _write_client(handler)
    with pytest.raises(Exception, match="unrecognised retCode"):
        await client.create_withdrawal(_dry_run())
    await client.close()


async def test_query_record_retries_transient_5xx_then_succeeds():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "GET"
        if calls == 1:
            return httpx.Response(503)
        return _bybit_response(
            0,
            result={"rows": [{"withdrawId": "BYBIT-WD-1", "status": "success", "txID": "0xabc"}]},
        )

    client = _write_client(handler)
    row = await client.query_record(withdraw_id="BYBIT-WD-1")
    assert calls == 2
    assert row["status"] == "success"
    await client.close()


async def test_query_record_no_match_returns_none():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _bybit_response(0, result={"rows": []})

    client = _write_client(handler)
    assert await client.query_record(withdraw_id="BYBIT-WD-404") is None
    await client.close()


# ---------------------------------------------------------------------------
# BybitLivePayoutProvider - read-only metadata + write client composition
# ---------------------------------------------------------------------------


def _intent(*, network="TRC20", destination=VALID_TRC20, external_reference=None) -> PayoutIntent:
    return PayoutIntent(
        id=uuid.uuid4(),
        asset="USDT",
        network=network,
        destination=destination,
        amount=Decimal("25"),
        fee_amount=Decimal("0"),
        external_reference=external_reference,
    )


def _fresh_network(*, withdraw_enabled=True) -> ExchangeWithdrawalNetwork:
    return ExchangeWithdrawalNetwork(
        provider="bybit",
        asset="USDT",
        chain="TRX",
        chain_type="TRC20",
        fixed_fee=Decimal("1"),
        percentage_fee=Decimal("0"),
        minimum_amount=Decimal("10"),
        maximum_amount=Decimal("100000"),
        decimal_places=6,
        withdraw_enabled=withdraw_enabled,
        received_at=datetime.now(UTC),
    )


class _FakeReadOnlyClient:
    def __init__(self, networks):
        self._networks = networks

    async def get_withdrawal_networks(self, asset):
        return self._networks


def _patch_read_only(monkeypatch, networks):
    monkeypatch.setattr(
        "app.services.exchange_private.runtime.get_bybit_private_client",
        lambda: _FakeReadOnlyClient(networks),
    )


async def test_execute_success_sets_fee_and_external_reference(monkeypatch):
    _patch_read_only(monkeypatch, [_fresh_network()])

    async def handler(request: httpx.Request) -> httpx.Response:
        return _bybit_response(0, result={"id": "BYBIT-WD-42"})

    provider = BybitLivePayoutProvider(write_client=_write_client(handler))
    intent = _intent()
    result = await provider.execute(intent)
    assert result.status == PayoutProviderResult.SUCCEEDED
    assert result.external_reference == "BYBIT-WD-42"
    assert intent.fee_amount == Decimal("1")


async def test_execute_refuses_non_trc20_network_without_any_write_attempt(monkeypatch):
    _patch_read_only(monkeypatch, [_fresh_network()])

    async def forbidden(request: httpx.Request) -> httpx.Response:
        pytest.fail("a BYBIT_UID (non-TRC20) intent must never reach the write client")

    provider = BybitLivePayoutProvider(write_client=_write_client(forbidden))
    result = await provider.execute(_intent(network="BYBIT_UID"))
    assert result.status == PayoutProviderResult.FAILED
    assert result.failure_code == "NETWORK_NOT_ALLOWED"


async def test_execute_duplicate_request_becomes_reconciliation_not_a_new_attempt(monkeypatch):
    _patch_read_only(monkeypatch, [_fresh_network()])

    async def handler(request: httpx.Request) -> httpx.Response:
        return _bybit_response(131082)

    provider = BybitLivePayoutProvider(write_client=_write_client(handler))
    result = await provider.execute(_intent())
    assert result.status == PayoutProviderResult.UNKNOWN
    assert result.failure_code == "DUPLICATE_REQUEST_REQUIRES_RECONCILIATION"


async def test_execute_permanent_failure_maps_to_failed(monkeypatch):
    _patch_read_only(monkeypatch, [_fresh_network()])

    async def handler(request: httpx.Request) -> httpx.Response:
        return _bybit_response(131093)

    provider = BybitLivePayoutProvider(write_client=_write_client(handler))
    result = await provider.execute(_intent())
    assert result.status == PayoutProviderResult.FAILED
    assert result.failure_code == "ADDRESS_NOT_IN_APPROVED_LIST"


async def test_execute_timeout_or_permission_failure_becomes_unknown_never_failed_or_succeeded(
    monkeypatch,
):
    _patch_read_only(monkeypatch, [_fresh_network()])

    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = BybitLivePayoutProvider(write_client=_write_client(timeout_handler))
    result = await provider.execute(_intent())
    assert result.status == PayoutProviderResult.UNKNOWN

    async def auth_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    provider2 = BybitLivePayoutProvider(write_client=_write_client(auth_handler))
    result2 = await provider2.execute(_intent())
    assert result2.status == PayoutProviderResult.UNKNOWN


async def test_execute_stale_metadata_blocks_before_any_write(monkeypatch):
    stale = _fresh_network()
    stale = ExchangeWithdrawalNetwork(
        provider=stale.provider,
        asset=stale.asset,
        chain=stale.chain,
        chain_type=stale.chain_type,
        fixed_fee=stale.fixed_fee,
        percentage_fee=stale.percentage_fee,
        minimum_amount=stale.minimum_amount,
        maximum_amount=stale.maximum_amount,
        decimal_places=stale.decimal_places,
        withdraw_enabled=stale.withdraw_enabled,
        received_at=datetime.now(UTC)
        - timedelta(seconds=settings.BYBIT_WITHDRAW_METADATA_MAX_AGE_SECONDS + 30),
    )
    _patch_read_only(monkeypatch, [stale])

    async def forbidden(request: httpx.Request) -> httpx.Response:
        pytest.fail("stale metadata must never reach the write client")

    provider = BybitLivePayoutProvider(write_client=_write_client(forbidden))
    result = await provider.execute(_intent())
    assert result.status == PayoutProviderResult.FAILED
    assert result.failure_code == "WITHDRAW_METADATA_STALE"


async def test_get_status_without_provider_reference_is_unknown():
    provider = BybitLivePayoutProvider()
    result = await provider.get_status(_intent())
    assert result.status == PayoutProviderResult.UNKNOWN
    assert result.failure_code == "NO_PROVIDER_REFERENCE_YET"


@pytest.mark.parametrize(
    ("bybit_status", "expected"),
    [
        ("success", PayoutProviderResult.SUCCEEDED),
        ("BlockchainConfirmed", PayoutProviderResult.SUCCEEDED),
        ("Reject", PayoutProviderResult.FAILED),
        ("Fail", PayoutProviderResult.FAILED),
        ("CancelByUser", PayoutProviderResult.FAILED),
        ("Pending", PayoutProviderResult.PENDING),
        ("SecurityCheck", PayoutProviderResult.PENDING),
        ("SomeFutureStatusWeDoNotKnowYet", PayoutProviderResult.UNKNOWN),
    ],
)
async def test_get_status_maps_bybit_status_and_fails_closed_on_unrecognised(
    bybit_status, expected
):
    async def handler(request: httpx.Request) -> httpx.Response:
        return _bybit_response(
            0, result={"rows": [{"withdrawId": "BYBIT-WD-1", "status": bybit_status}]}
        )

    provider = BybitLivePayoutProvider(write_client=_write_client(handler))
    result = await provider.get_status(_intent(external_reference="BYBIT-WD-1"))
    assert result.status == expected


async def test_get_status_record_not_found_is_unknown_not_assumed_failed():
    async def handler(request: httpx.Request) -> httpx.Response:
        return _bybit_response(0, result={"rows": []})

    provider = BybitLivePayoutProvider(write_client=_write_client(handler))
    result = await provider.get_status(_intent(external_reference="BYBIT-WD-missing"))
    assert result.status == PayoutProviderResult.UNKNOWN
    assert result.failure_code == "RECORD_NOT_FOUND"


# ---------------------------------------------------------------------------
# ControlledPayoutService live-mode gates (readiness, cooldown, disabled)
# ---------------------------------------------------------------------------


async def _make_live_intent(db_session, make_account, make_merchant_wallet, client, monkeypatch):
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

    response = await client.post(
        "/merchant/withdrawals",
        json={"amount": "25", "destination_type": "usdt_trc20_address", "destination": VALID_TRC20},
        headers=_headers(merchant),
    )
    assert response.status_code == 201

    account_repo = AccountRepository(db_session)
    wallet_service = WalletService(
        WalletRepository(db_session), LedgerRepository(db_session), account_repo
    )
    service = ControlledPayoutService(
        payout_repo,
        WithdrawalRepository(db_session),
        risk_repo,
        wallet_service,
        account_repo,
    )
    withdrawal = (
        await db_session.execute(
            select(MerchantWithdrawal).where(MerchantWithdrawal.merchant_id == merchant.id)
        )
    ).scalar_one()
    intent = await service.create_for_withdrawal(withdrawal)
    assert intent.provider_mode == "live"
    assert intent.provider_name == "bybit"
    await service.approve(intent.id, owner_a)
    await service.approve(intent.id, owner_b)
    await db_session.refresh(intent)
    assert intent.status == PayoutStatus.APPROVED.value
    return intent, owner_a, service, payout_repo, risk_repo, account_repo, wallet_service


async def test_live_execute_blocked_when_destination_disabled_after_intent_creation(
    db_session, make_account, make_merchant_wallet, client, monkeypatch
):
    """create_for_withdrawal auto-registers a beneficiary-scoped
    PayoutDestination from the withdrawal's own address - so the meaningful
    "not approved" scenario now is Owner revoking that specific destination
    AFTER the intent already exists, not "nothing was ever registered"."""
    intent, owner, service, *_ = await _make_live_intent(
        db_session, make_account, make_merchant_wallet, client, monkeypatch
    )
    monkeypatch.setattr(settings, "BYBIT_WRITE_ENABLED", True)
    monkeypatch.setattr(settings, "BYBIT_WRITE_API_KEY", SecretStr("write-key"))
    monkeypatch.setattr(settings, "BYBIT_WRITE_API_SECRET", SecretStr("write-secret"))
    monkeypatch.setattr(settings, "BYBIT_WRITE_PERMISSION_VERIFIED", True)
    monkeypatch.setattr(settings, "BYBIT_WRITE_IP_WHITELIST_VERIFIED", True)
    monkeypatch.setattr(settings, "BYBIT_LIVE_RECONCILIATION_VERIFIED", True)
    security = PayoutSecurityRepository(db_session)
    destinations = await security.destinations_for_beneficiary(intent.beneficiary_account_id)
    assert len(destinations) == 1, "create_for_withdrawal should have auto-registered exactly one"
    # Keep the aggregate address_allowlist_configured readiness check True by
    # leaving an unrelated, different-beneficiary destination enabled - this
    # isolates the per-transaction (beneficiary, fingerprint) check under
    # test from the separate aggregate-count readiness check.
    from app.models.payout import PayoutDestination

    await security.save_destination(
        PayoutDestination(
            label="unrelated",
            asset="USDT",
            network="TRC20",
            address="TXYZ9nRRqPk8y7QAtJvzwj1AmVKUyzTLzT",
            masked_address="TXYZ9...",
            beneficiary_account_id=owner.id,
            fingerprint="e" * 64,
            enabled=True,
            created_by_account_id=owner.id,
        )
    )
    destinations[0].enabled = False
    await db_session.flush()
    readiness = await LivePayoutReadinessService(
        security, PayoutRepository(db_session), RiskRepository(db_session)
    ).evaluate()
    assert readiness.ready is True, readiness.blocking_reasons
    with pytest.raises(PayoutSafetyError, match="DESTINATION_NOT_APPROVED_FOR_BENEFICIARY"):
        await service.queue(intent.id, owner, outcome=PayoutSimulationOutcome.SUCCEEDED)


async def test_live_execute_blocked_when_payout_provider_mode_flips_back_to_disabled(
    db_session, make_account, make_merchant_wallet, client, monkeypatch
):
    intent, owner, service, *_ = await _make_live_intent(
        db_session, make_account, make_merchant_wallet, client, monkeypatch
    )
    monkeypatch.setattr(settings, "PAYOUT_PROVIDER_MODE", "disabled")
    with pytest.raises(PayoutSafetyError, match="LIVE_PROVIDER_DISABLED"):
        await service.queue(intent.id, owner, outcome=PayoutSimulationOutcome.SUCCEEDED)


async def test_live_execute_cooldown_blocks_concurrent_same_coin_chain_submission(
    db_session, make_account, make_merchant_wallet, client, monkeypatch
):
    (
        intent,
        owner,
        service,
        payout_repo,
        risk_repo,
        account_repo,
        wallet_service,
    ) = await _make_live_intent(db_session, make_account, make_merchant_wallet, client, monkeypatch)
    monkeypatch.setattr(settings, "BYBIT_WRITE_ENABLED", True)
    monkeypatch.setattr(settings, "BYBIT_WRITE_API_KEY", SecretStr("write-key"))
    monkeypatch.setattr(settings, "BYBIT_WRITE_API_SECRET", SecretStr("write-secret"))
    monkeypatch.setattr(settings, "BYBIT_WRITE_PERMISSION_VERIFIED", True)
    monkeypatch.setattr(settings, "BYBIT_WRITE_IP_WHITELIST_VERIFIED", True)
    monkeypatch.setattr(settings, "BYBIT_LIVE_RECONCILIATION_VERIFIED", True)
    security = PayoutSecurityRepository(db_session)

    # create_for_withdrawal already auto-registered a beneficiary-scoped
    # PayoutDestination for this exact address - no manual seeding needed.
    readiness = await LivePayoutReadinessService(security, payout_repo, risk_repo).evaluate()
    assert readiness.ready is True, readiness.blocking_reasons

    class _AlwaysLimited:
        def __init__(self):
            self.calls = 0

        async def is_rate_limited(self, key, max_requests, window_seconds, fail_mode=None):
            self.calls += 1
            return True

    limiter = _AlwaysLimited()
    gated_service = ControlledPayoutService(
        payout_repo,
        WithdrawalRepository(db_session),
        risk_repo,
        wallet_service,
        account_repo,
        rate_limiter=limiter,
    )
    await gated_service.queue(intent.id, owner, outcome=PayoutSimulationOutcome.SUCCEEDED)
    assert limiter.calls == 0, (
        "queue() performs no network submission and must not consume the cooldown slot"
    )
    with pytest.raises(PayoutSafetyError, match="BYBIT_WITHDRAW_COOLDOWN_ACTIVE"):
        await gated_service.execute(intent.id, owner.id)
    assert limiter.calls == 1


async def test_live_execute_end_to_end_success_finalizes_withdrawal(
    db_session, make_account, make_merchant_wallet, client, monkeypatch
):
    (
        intent,
        owner,
        service,
        payout_repo,
        risk_repo,
        account_repo,
        wallet_service,
    ) = await _make_live_intent(db_session, make_account, make_merchant_wallet, client, monkeypatch)
    monkeypatch.setattr(settings, "BYBIT_WRITE_ENABLED", True)
    monkeypatch.setattr(settings, "BYBIT_WRITE_API_KEY", SecretStr("write-key"))
    monkeypatch.setattr(settings, "BYBIT_WRITE_API_SECRET", SecretStr("write-secret"))
    monkeypatch.setattr(settings, "BYBIT_WRITE_PERMISSION_VERIFIED", True)
    monkeypatch.setattr(settings, "BYBIT_WRITE_IP_WHITELIST_VERIFIED", True)
    monkeypatch.setattr(settings, "BYBIT_LIVE_RECONCILIATION_VERIFIED", True)
    # create_for_withdrawal already auto-registered a beneficiary-scoped
    # PayoutDestination for this exact address - no manual seeding needed.

    class _AlwaysAllowed:
        async def is_rate_limited(self, key, max_requests, window_seconds, fail_mode=None):
            return False

    class _StubProvider:
        async def prepare(self, intent):
            return None

        async def execute(self, intent):
            intent.fee_amount = Decimal("1")
            return ProviderPayoutResult(
                PayoutProviderResult.SUCCEEDED, external_reference="BYBIT-WD-777"
            )

        async def get_status(self, intent):
            return ProviderPayoutResult(
                PayoutProviderResult.SUCCEEDED, external_reference="BYBIT-WD-777"
            )

    stub_service = ControlledPayoutService(
        payout_repo,
        WithdrawalRepository(db_session),
        risk_repo,
        wallet_service,
        account_repo,
        provider=_StubProvider(),
        rate_limiter=_AlwaysAllowed(),
    )
    await stub_service.queue(intent.id, owner, outcome=PayoutSimulationOutcome.SUCCEEDED)
    finished = await stub_service.execute(intent.id, owner.id)
    assert finished.status == PayoutStatus.SUCCEEDED.value
    assert finished.external_reference == "BYBIT-WD-777"
    withdrawal = await WithdrawalRepository(db_session).get_by_id(intent.withdrawal_id)
    assert withdrawal.status.value == "paid"


async def test_live_intent_tamper_after_approval_is_blocked_for_amount_destination_network(
    db_session, make_account, make_merchant_wallet, client, monkeypatch
):
    intent, owner, service, *_ = await _make_live_intent(
        db_session, make_account, make_merchant_wallet, client, monkeypatch
    )
    for field, value in (
        ("amount", Decimal("999")),
        ("destination", "T" + "z" * 33),
        ("network", "BYBIT_UID"),
    ):
        original = getattr(intent, field)
        setattr(intent, field, value)
        with pytest.raises(PayoutSafetyError, match="PAYOUT_INTENT_CHANGED"):
            await service.queue(intent.id, owner, outcome=PayoutSimulationOutcome.SUCCEEDED)
        setattr(intent, field, original)
