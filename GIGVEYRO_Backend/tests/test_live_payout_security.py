import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.config import Settings, settings
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.payout import PayoutProviderResult
from app.models.audit import AuditLog
from app.models.payout import PayoutIntent
from app.repositories.payout import PayoutRepository
from app.services.exchange_private.bybit import BybitPrivateClient
from app.services.payout import intent_hash
from app.services.payout_live.bybit import (
    BYBIT_WITHDRAW_PATH,
    BybitLivePayoutProvider,
    BybitWithdrawalMetadata,
    LivePayoutSecurityError,
    build_bybit_withdrawal_dry_run,
    sign_post_dry_run,
    validate_post_payout_reserve,
    validate_tron_base58check,
)

VALID_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


def _headers(account):
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


def _intent(*, asset="USDT", network="TRC20", address=VALID_TRC20, amount="25"):
    return PayoutIntent(
        id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        asset=asset,
        network=network,
        destination=address,
        amount=Decimal(amount),
    )


def _metadata(*, observed_at=None):
    return BybitWithdrawalMetadata(
        asset="USDT",
        network="TRC20",
        bybit_chain="TRX",
        fixed_fee=Decimal("1"),
        percentage_fee=Decimal("0.01"),
        minimum_amount=Decimal("10"),
        maximum_amount=Decimal("1000"),
        decimal_places=6,
        withdraw_enabled=True,
        observed_at=observed_at or datetime(2026, 8, 30, tzinfo=UTC),
    )


def test_tron_checksum_and_dry_run_request_are_deterministic():
    now = datetime(2026, 8, 30, tzinfo=UTC)
    validate_tron_base58check(VALID_TRC20)
    draft = build_bybit_withdrawal_dry_run(
        intent=_intent(), metadata=_metadata(), now=now, max_metadata_age_seconds=60
    )
    assert draft.path == BYBIT_WITHDRAW_PATH
    assert draft.request_id == "11111111222233334444555555555555"
    assert len(draft.request_id) == 32 and draft.request_id.isalnum()
    assert draft.recipient_amount == Decimal("25")
    assert draft.network_fee == Decimal("1.252525252525252525252525252")
    assert draft.treasury_impact == Decimal("26.25252525252525252525252525")
    payload = json.loads(draft.body)
    assert payload == {
        "accountType": "UTA",
        "address": VALID_TRC20,
        "amount": "25",
        "chain": "TRX",
        "coin": "USDT",
        "feeType": 0,
        "forceChain": 1,
        "requestId": "11111111222233334444555555555555",
        "timestamp": 1788048000000,
    }
    assert VALID_TRC20 not in repr(draft)


def test_dry_run_signing_uses_dummy_secrets_without_repr_leakage():
    first = sign_post_dry_run(
        timestamp_ms=1788048000000,
        recv_window_ms=5000,
        api_key=SecretStr("dummy-key"),
        api_secret=SecretStr("dummy-secret"),
        body='{"coin":"USDT"}',
    )
    second = sign_post_dry_run(
        timestamp_ms=1788048000000,
        recv_window_ms=5000,
        api_key=SecretStr("dummy-key"),
        api_secret=SecretStr("dummy-secret"),
        body='{"coin":"USDT"}',
    )
    assert first.signature == second.signature
    assert len(first.signature) == 64
    assert "dummy-key" not in repr(first)
    assert "dummy-secret" not in repr(first)
    assert first.signature not in repr(first)


def test_live_approval_hash_binds_provider_identity_and_destination():
    intent = SimpleNamespace(
        withdrawal_id=uuid.uuid4(),
        requester_account_id=uuid.uuid4(),
        beneficiary_account_id=uuid.uuid4(),
        asset="USDT",
        amount=Decimal("25"),
        network="TRC20",
        destination=VALID_TRC20,
        fee_amount=Decimal("1"),
        risk_policy_version=1,
        risk_decision="allow",
        risk_reason=None,
        treasury_generated_at=datetime(2026, 8, 30, tzinfo=UTC),
        approval_policy_version=1,
        required_approvals=2,
        provider_name="bybit",
        provider_mode="live",
        idempotency_key="payout:test",
    )
    original = intent_hash(intent)
    intent.provider_name = "another_provider"
    assert intent_hash(intent) != original
    intent.provider_name = "bybit"
    intent.destination = "TPYmHEhy5n8TCEfYGqW2rPxsghSfzghPDn"
    assert intent_hash(intent) != original


@pytest.mark.parametrize(
    ("intent", "metadata", "error"),
    [
        (_intent(asset="BTC"), _metadata(), "ASSET_NOT_ALLOWED"),
        (_intent(network="ETH"), _metadata(), "NETWORK_NOT_ALLOWED"),
        (_intent(address="T" * 34), _metadata(), "INVALID_TRC20_CHECKSUM"),
        (
            _intent(),
            _metadata(observed_at=datetime(2026, 8, 29, tzinfo=UTC)),
            "WITHDRAW_METADATA_STALE",
        ),
        (_intent(amount="1"), _metadata(), "BELOW_PROVIDER_WITHDRAW_MINIMUM"),
    ],
)
def test_dry_run_builder_fails_closed(intent, metadata, error):
    with pytest.raises(LivePayoutSecurityError, match=error):
        build_bybit_withdrawal_dry_run(
            intent=intent,
            metadata=metadata,
            now=datetime(2026, 8, 30, tzinfo=UTC),
            max_metadata_age_seconds=60,
        )


def test_post_payout_reserve_includes_amount_and_fee():
    assert validate_post_payout_reserve(
        observed_reserve=Decimal("100"),
        required_reserve=Decimal("50"),
        treasury_impact=Decimal("26"),
    ) == Decimal("74")
    with pytest.raises(LivePayoutSecurityError, match="POST_PAYOUT_RESERVE_INSUFFICIENT"):
        validate_post_payout_reserve(
            observed_reserve=Decimal("75"),
            required_reserve=Decimal("50"),
            treasury_impact=Decimal("26"),
        )


async def test_live_provider_never_writes_without_read_only_metadata(monkeypatch):
    """With no read-only runtime initialised (as in this process) and no
    write credentials configured, execute() must fail closed - as a FAILED
    ProviderPayoutResult, never a raised exception left for the caller to
    forget to catch, and never an outbound HTTP write."""

    async def forbidden(*args, **kwargs):
        pytest.fail("an outbound HTTP write was attempted")

    monkeypatch.setattr(httpx.AsyncClient, "post", forbidden)
    provider = BybitLivePayoutProvider()
    result = await provider.execute(_intent())
    assert result.status == PayoutProviderResult.FAILED
    assert result.failure_code == "READ_ONLY_CLIENT_UNAVAILABLE"
    assert "mode='LIVE'" in repr(provider)
    assert "configured=False" in repr(provider)


async def test_read_only_bybit_metadata_uses_get_only():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v5/asset/coin/query-info"
        return httpx.Response(
            200,
            json={
                "retCode": 0,
                "retMsg": "success",
                "result": {
                    "rows": [
                        {
                            "coin": "USDT",
                            "chains": [
                                {
                                    "chain": "TRX",
                                    "chainType": "TRC20",
                                    "withdrawFee": "1",
                                    "withdrawPercentageFee": "0",
                                    "withdrawMin": "10",
                                    "withdrawMax": "-1",
                                    "minAccuracy": "6",
                                    "chainWithdraw": "1",
                                }
                            ],
                        }
                    ]
                },
                "time": 1788048000000,
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = BybitPrivateClient(
        base_url="https://api.bybit.test",
        api_key="dummy-read-key",
        api_secret="dummy-read-secret",
        recv_window_ms=5000,
        timeout_seconds=1,
        max_retries=0,
        client=http,
        clock_ms=lambda: 1788048000000,
    )
    networks = await client.get_withdrawal_networks("USDT")
    assert len(networks) == 1
    assert networks[0].chain == "TRX"
    assert networks[0].maximum_amount is None
    assert not any(
        name.startswith(("create_", "withdraw", "transfer", "post"))
        for name in dir(BybitPrivateClient)
    )
    await http.aclose()


async def test_readiness_is_not_ready_and_allowlist_is_owner_only(client, db_session, make_account):
    owner = await make_account(role=UserRole.OWNER)
    merchant = await make_account(role=UserRole.MERCHANT)
    denied = await client.get("/api/v1/owner/payout-readiness", headers=_headers(merchant))
    assert denied.status_code == 403

    readiness = await client.get("/api/v1/owner/payout-readiness", headers=_headers(owner))
    assert readiness.status_code == 200
    body = readiness.json()
    assert body["ready"] is False
    assert body["checks"]["write_network_transport_available"] is False
    assert body["checks"]["dual_approval_ready"] is False
    assert "LIVE_DISABLED" in body["capabilities"]
    assert "WRITE_NETWORK_TRANSPORT_DISABLED" in body["blocking_reasons"]
    assert "NO_APPROVED_DESTINATION" in body["blocking_reasons"]

    denied_create = await client.post(
        "/api/v1/owner/payout-addresses",
        json={"label": "Treasury", "asset": "USDT", "network": "TRC20", "address": VALID_TRC20},
        headers=_headers(merchant),
    )
    assert denied_create.status_code == 403
    created = await client.post(
        "/api/v1/owner/payout-addresses",
        json={"label": "Treasury", "asset": "USDT", "network": "TRC20", "address": VALID_TRC20},
        headers=_headers(owner),
    )
    assert created.status_code == 201
    payload = created.json()
    assert "address" not in payload
    assert VALID_TRC20 not in created.text
    assert payload["masked_address"].startswith("TR7NH")
    assert len(payload["fingerprint"]) == 64

    refreshed = await client.get("/api/v1/owner/payout-readiness", headers=_headers(owner))
    assert refreshed.json()["checks"]["address_allowlist_configured"] is True
    assert "NO_APPROVED_DESTINATION" not in refreshed.json()["blocking_reasons"]
    disabled = await client.post(
        f"/api/v1/owner/payout-addresses/{payload['id']}/disable", headers=_headers(owner)
    )
    assert disabled.status_code == 200 and disabled.json()["enabled"] is False
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action.in_(("payout_address.created", "payout_address.disabled")))
        )
        == 2
    )


async def test_live_dual_approval_readiness_requires_two_by_default(
    client, db_session, make_account
):
    owner = await make_account(role=UserRole.OWNER)
    policy = await PayoutRepository(db_session).active_policy()
    policy.default_required_approvals = 2
    policy.high_value_required_approvals = 2
    response = await client.get("/api/v1/owner/payout-readiness", headers=_headers(owner))
    assert response.status_code == 200
    assert response.json()["checks"]["dual_approval_ready"] is True
    assert response.json()["ready"] is False


def test_actual_write_configuration_remains_disabled():
    assert settings.PAYOUT_ENABLED is False
    assert settings.PAYOUT_PROVIDER_MODE == "disabled"
    assert settings.BYBIT_WRITE_ENABLED is False
    assert settings.BYBIT_WRITE_API_KEY.get_secret_value() == ""
    assert settings.BYBIT_WRITE_API_SECRET.get_secret_value() == ""


def test_write_enabled_requires_its_own_separate_credentials():
    with pytest.raises(ValueError, match="requires BYBIT_WRITE_API_KEY"):
        Settings(BYBIT_WRITE_ENABLED=True)


def test_write_key_cannot_reuse_the_read_only_treasury_key():
    with pytest.raises(ValueError, match="separate credential from the read-only"):
        Settings(
            BYBIT_WRITE_ENABLED=True,
            BYBIT_WRITE_API_KEY=SecretStr("same-key"),
            BYBIT_WRITE_API_SECRET=SecretStr("write-secret"),
            BYBIT_API_KEY=SecretStr("same-key"),
            BYBIT_API_SECRET=SecretStr("read-secret"),
        )


@pytest.mark.parametrize(
    "missing_flag",
    [
        "BYBIT_WRITE_ENABLED",
        "PAYOUT_ENABLED",
        "BYBIT_WRITE_PERMISSION_VERIFIED",
        "BYBIT_WRITE_IP_WHITELIST_VERIFIED",
    ],
)
def test_live_mode_requires_every_operator_flag_simultaneously(missing_flag):
    """Live mode is a hard multi-flag AND - missing any single one of the
    operator-verified preconditions must still block boot, not just warn."""
    live_ready_kwargs = {
        "PAYOUT_PROVIDER_MODE": "live",
        "PAYOUT_ENABLED": True,
        "BYBIT_WRITE_ENABLED": True,
        "BYBIT_WRITE_API_KEY": SecretStr("write-key"),
        "BYBIT_WRITE_API_SECRET": SecretStr("write-secret"),
        "BYBIT_WRITE_PERMISSION_VERIFIED": True,
        "BYBIT_WRITE_IP_WHITELIST_VERIFIED": True,
    }
    live_ready_kwargs[missing_flag] = False
    with pytest.raises(ValueError, match="PAYOUT_PROVIDER_MODE=live requires"):
        Settings(**live_ready_kwargs)


def test_all_flags_together_boot_successfully_but_stay_the_operators_responsibility():
    """Proves the gate is real (not a permanent block) without ever touching
    the actual deployment's .env - PAYOUT_ENABLED/BYBIT_WRITE_ENABLED remain
    False there unless an operator deliberately sets them."""
    live = Settings(
        PAYOUT_PROVIDER_MODE="live",
        PAYOUT_ENABLED=True,
        BYBIT_WRITE_ENABLED=True,
        BYBIT_WRITE_API_KEY=SecretStr("write-key"),
        BYBIT_WRITE_API_SECRET=SecretStr("write-secret"),
        BYBIT_WRITE_PERMISSION_VERIFIED=True,
        BYBIT_WRITE_IP_WHITELIST_VERIFIED=True,
    )
    assert live.PAYOUT_PROVIDER_MODE == "live"
    assert settings.PAYOUT_PROVIDER_MODE == "disabled"
    assert settings.PAYOUT_ENABLED is False
    assert settings.BYBIT_WRITE_ENABLED is False
