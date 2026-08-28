import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.api.fiat_deps import get_conversion_rate_dependency
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.fees import FeeType
from app.models.audit import AuditLog
from app.models.fees import FeeSnapshot, OwnerProfitEntry
from app.models.fiat_wallet import FiatConversion, FiatWalletBalance
from app.services.fees import FeeCalculator, FeePolicyValidationError, FeeTerms
from tests.test_fiat_wallets import StubConversionRates


def _headers(account):
    return {"Authorization": f"Bearer {create_access_token(account.id, role=account.role)}"}


def _component(*, enabled=False, bps=0, fixed="0", minimum=None, maximum=None, payer=None):
    return {
        "enabled": enabled,
        "percent_bps": bps,
        "fixed_fee": fixed,
        "min_fee": minimum,
        "max_fee": maximum,
        "payer": payer,
    }


def _policy_payload(*, conversion=None, deal=None, withdrawal=None, merchant=None):
    return {
        "components": {
            "deal_fee": deal or _component(),
            "fiat_conversion_spread": conversion or _component(payer="USER"),
            "withdrawal_fee": withdrawal or _component(),
            "merchant_fee": merchant or _component(),
        }
    }


@pytest.mark.parametrize(
    ("amount", "terms", "expected"),
    [
        ("0", FeeTerms(False, 0, Decimal("0")), ("0", "0")),
        ("0.00000001", FeeTerms(True, 1, Decimal("0")), ("0", "0.00000001")),
        ("1000", FeeTerms(True, 100, Decimal("0")), ("10", "990")),
        ("1000", FeeTerms(True, 25, Decimal("2.5")), ("5", "995")),
        ("1000", FeeTerms(True, 1, Decimal("0"), min_fee=Decimal("2")), ("2", "998")),
        ("1000", FeeTerms(True, 500, Decimal("0"), max_fee=Decimal("10")), ("10", "990")),
        ("999999999", FeeTerms(True, 1, Decimal("0")), ("99999.9999", "999899999.0001")),
    ],
)
def test_fee_calculator_rounding_boundaries_and_disabled(amount, terms, expected):
    result = FeeCalculator.calculate(Decimal(amount), terms)
    assert result.total_fee == Decimal(expected[0])
    assert result.net == Decimal(expected[1])
    assert result.gross == result.total_fee + result.net


@pytest.mark.parametrize(
    "amount,terms",
    [
        (Decimal("NaN"), FeeTerms(True, 1, Decimal("0"))),
        (Decimal("-1"), FeeTerms(True, 1, Decimal("0"))),
        (Decimal("1"), FeeTerms(True, 5001, Decimal("0"))),
        (Decimal("1"), FeeTerms(True, 0, Decimal("2"))),
        (Decimal("1"), FeeTerms(True, 0, Decimal("0"), Decimal("2"), Decimal("1"))),
    ],
)
def test_fee_calculator_rejects_unsafe_values(amount, terms):
    with pytest.raises(FeePolicyValidationError):
        FeeCalculator.calculate(amount, terms)


async def _create_and_activate(client, owner, payload):
    created = await client.post(
        "/api/v1/owner/fees/policies", json=payload, headers=_headers(owner)
    )
    assert created.status_code == 201, created.text
    activated = await client.post(
        f"/api/v1/owner/fees/policies/{created.json()['id']}/activate",
        headers=_headers(owner),
    )
    assert activated.status_code == 200, activated.text
    return activated.json()


async def test_default_policy_is_disabled_and_fee_admin_profit_are_owner_only(client, make_account):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    merchant = await make_account(role=UserRole.MERCHANT)
    policy = await client.get("/api/v1/owner/fees/policy", headers=_headers(owner))
    assert policy.status_code == 200
    assert policy.json()["version"] == 1
    assert all(not item["enabled"] for item in policy.json()["components"])
    for actor in (user, merchant):
        for path in (
            "/api/v1/owner/fees/policy",
            "/api/v1/owner/profit/summary",
            "/api/v1/owner/profit/entries",
        ):
            assert (await client.get(path, headers=_headers(actor))).status_code == 403
        assert (
            await client.post(
                "/api/v1/owner/fees/policies",
                json=_policy_payload(),
                headers=_headers(actor),
            )
        ).status_code == 403


async def test_policy_validation_audit_and_unenforced_component_activation_guard(
    client, make_account, db_session
):
    owner = await make_account(role=UserRole.OWNER)
    float_input = _policy_payload(conversion=_component(enabled=True, bps=100, fixed=0.1))
    assert (
        await client.post("/api/v1/owner/fees/policies", json=float_input, headers=_headers(owner))
    ).status_code == 422
    draft = await client.post(
        "/api/v1/owner/fees/policies",
        json=_policy_payload(deal=_component(enabled=True, bps=100, payer="MERCHANT")),
        headers=_headers(owner),
    )
    assert draft.status_code == 201
    rejected = await client.post(
        f"/api/v1/owner/fees/policies/{draft.json()['id']}/activate",
        headers=_headers(owner),
    )
    assert rejected.status_code == 422
    assert "deal_fee" in rejected.json()["detail"]
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "fee_policy.created")
        )
        == 1
    )


async def test_policy_validation_uses_terms_not_sample_amount_and_fiat_payer_is_fixed(
    client, make_account
):
    owner = await make_account(role=UserRole.OWNER)
    large_fixed = await client.post(
        "/api/v1/owner/fees/policies",
        json=_policy_payload(conversion=_component(enabled=True, fixed="2000", payer="USER")),
        headers=_headers(owner),
    )
    assert large_fixed.status_code == 201, large_fixed.text

    wrong_payer = await client.post(
        "/api/v1/owner/fees/policies",
        json=_policy_payload(conversion=_component(enabled=True, bps=100, payer="MERCHANT")),
        headers=_headers(owner),
    )
    assert wrong_payer.status_code == 201, wrong_payer.text
    rejected = await client.post(
        f"/api/v1/owner/fees/policies/{wrong_payer.json()['id']}/activate",
        headers=_headers(owner),
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "Fiat conversion spread payer must be USER"


async def test_conversion_spread_is_transparent_balanced_idempotent_and_immutable(
    client, make_account, db_session
):
    from app.main import app

    rates = StubConversionRates()
    app.dependency_overrides[get_conversion_rate_dependency] = lambda: rates
    try:
        owner = await make_account(role=UserRole.OWNER)
        user = await make_account(role=UserRole.USER)
        active = await _create_and_activate(
            client,
            owner,
            _policy_payload(conversion=_component(enabled=True, bps=100, fixed="1", payer="USER")),
        )
        assert active["version"] == 2
        preview = await client.post(
            "/owner/fiat-conversions/preview",
            json={"from_currency": "TJS", "to_currency": "RUB", "source_amount": "100"},
            headers=_headers(owner),
        )
        assert preview.status_code == 200
        preview_body = preview.json()
        assert Decimal(preview_body["gross_destination_amount"]) == Decimal("901.71325500")
        assert Decimal(preview_body["fee_amount"]) == Decimal("10.01713255")
        assert Decimal(preview_body["destination_amount"]) == Decimal("891.69612245")
        assert preview_body["reference_rate"] != preview_body["effective_rate"]

        allocated = await client.post(
            f"/owner/accounts/{user.id}/fiat-wallets/allocate",
            json={"currency": "TJS", "amount": "100", "idempotency_key": "fee-seed-tjs"},
            headers=_headers(owner),
        )
        assert allocated.status_code == 200
        payload = {
            "from_currency": "TJS",
            "to_currency": "RUB",
            "source_amount": "100",
            "idempotency_key": "fee-conversion-idempotent",
        }
        url = f"/owner/accounts/{user.id}/fiat-conversions"
        first = await client.post(url, json=payload, headers=_headers(owner))
        second = await client.post(url, json=payload, headers=_headers(owner))
        assert first.status_code == second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        conversion_id = uuid.UUID(first.json()["id"])
        assert first.json()["fee_policy_version"] == 2
        assert Decimal(first.json()["fee_amount"]) == Decimal("10.01713255")

        snapshot = await db_session.scalar(
            select(FeeSnapshot).where(FeeSnapshot.source_id == conversion_id)
        )
        profit = await db_session.scalar(
            select(OwnerProfitEntry).where(OwnerProfitEntry.source_id == conversion_id)
        )
        assert snapshot.gross_amount == snapshot.fee_amount + snapshot.net_amount
        assert snapshot.policy_version == profit.policy_version == 2
        assert snapshot.fee_amount == profit.fee_amount == Decimal("10.01713255")
        assert (
            await db_session.scalar(
                select(func.count())
                .select_from(OwnerProfitEntry)
                .where(OwnerProfitEntry.source_id == conversion_id)
            )
            == 1
        )

        await _create_and_activate(client, owner, _policy_payload())
        await db_session.refresh(snapshot)
        await db_session.refresh(profit)
        assert snapshot.policy_version == profit.policy_version == 2
        assert snapshot.fee_amount == Decimal("10.01713255")
        conversion = await db_session.get(FiatConversion, conversion_id)
        assert conversion.fee_policy_version == 2

        summary = await client.get("/api/v1/owner/profit/summary", headers=_headers(owner))
        assert summary.status_code == 200
        assert any(
            item["fee_type"] == FeeType.FIAT_CONVERSION.value
            for item in summary.json()["periods"]["all"]
        )
        history = await client.get(
            f"/api/v1/owner/profit/entries?source_id={conversion_id}",
            headers=_headers(owner),
        )
        assert history.json()["total"] == 1
        assert await db_session.scalar(
            select(FiatWalletBalance.available).where(
                FiatWalletBalance.account_id == user.id,
                FiatWalletBalance.currency == "RUB",
            )
        ) == Decimal("891.69612245")
    finally:
        app.dependency_overrides.pop(get_conversion_rate_dependency, None)


async def test_disabled_policy_preserves_exact_legacy_conversion_behavior(client, make_account):
    from app.main import app

    rates = StubConversionRates()
    app.dependency_overrides[get_conversion_rate_dependency] = lambda: rates
    try:
        owner = await make_account(role=UserRole.OWNER)
        user = await make_account(role=UserRole.USER)
        await client.post(
            f"/owner/accounts/{user.id}/fiat-wallets/allocate",
            json={"currency": "TJS", "amount": "100", "idempotency_key": "legacy-seed"},
            headers=_headers(owner),
        )
        converted = await client.post(
            f"/owner/accounts/{user.id}/fiat-conversions",
            json={
                "from_currency": "TJS",
                "to_currency": "RUB",
                "source_amount": "100",
                "idempotency_key": "legacy-conversion",
            },
            headers=_headers(owner),
        )
        assert converted.status_code == 200
        body = converted.json()
        assert body["fee_amount"] == "0.00000000"
        assert body["destination_amount"] == "901.71325500"
        assert body["exchange_rate"] == body["reference_rate"] == body["effective_rate"]
    finally:
        app.dependency_overrides.pop(get_conversion_rate_dependency, None)
