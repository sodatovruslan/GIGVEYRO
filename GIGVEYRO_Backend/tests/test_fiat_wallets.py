import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.api.fiat_deps import get_conversion_rate_dependency
from app.core.security import create_access_token
from app.enums.account import UserRole
from app.enums.notification import NotificationType
from app.enums.wallet import Currency, FiatLedgerEntryType
from app.main import app
from app.models.account import Account
from app.models.audit import AuditLog
from app.models.fiat_wallet import FiatConversion, FiatLedgerEntry, FiatWalletBalance
from app.models.notification import Notification
from app.models.realtime import RealtimeOutbox
from app.realtime.contracts import RealtimeEventName
from app.services.fiat_rate.errors import FiatProviderUnavailable
from app.services.fiat_rate.models import FiatConversionQuote, FiatSourceType


def _headers(account) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(account.id, role=account.role)}"
    }


class StubConversionRates:
    def __init__(self, rub_tjs: str = "0.11090000") -> None:
        self.rub_tjs = Decimal(rub_tjs)

    async def get_quote(
        self, from_currency: Currency, to_currency: Currency
    ) -> FiatConversionQuote:
        rate = (
            self.rub_tjs
            if from_currency == Currency.RUB
            else (Decimal(1) / self.rub_tjs).quantize(Decimal("0.00000001"))
        )
        now = datetime.now(UTC)
        return FiatConversionQuote(
            from_currency=from_currency.value,
            to_currency=to_currency.value,
            rate=rate,
            provider="nbt",
            published_at=now,
            received_at=now,
            source_type=FiatSourceType.OFFICIAL,
            provider_nominal=Decimal("1"),
            provider_rate=self.rub_tjs,
            policy_version="test-v1",
            mode="official",
            is_stale=False,
        )


class UnavailableConversionRates:
    async def get_quote(self, from_currency: Currency, to_currency: Currency):
        raise FiatProviderUnavailable("NBT unavailable")


@pytest.fixture
def conversion_rates():
    rates = StubConversionRates()
    app.dependency_overrides[get_conversion_rate_dependency] = lambda: rates
    yield rates
    app.dependency_overrides.pop(get_conversion_rate_dependency, None)


async def test_user_initial_fiat_balances_are_read_only_zero_without_rows(
    client, make_account, db_session, conversion_rates
):
    user = await make_account(role=UserRole.USER)
    response = await client.get("/fiat-wallets", headers=_headers(user))
    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "currency": "TJS",
            "available": "0.00000000",
            "updated_at": response.json()["items"][0]["updated_at"],
        },
        {
            "currency": "RUB",
            "available": "0.00000000",
            "updated_at": response.json()["items"][1]["updated_at"],
        },
    ]
    count = await db_session.scalar(
        select(func.count()).select_from(FiatWalletBalance).where(
            FiatWalletBalance.account_id == user.id
        )
    )
    assert count == 0
    assert (await client.post("/fiat-wallets", headers=_headers(user))).status_code == 405


@pytest.mark.parametrize(("currency", "amount"), [("TJS", "1000"), ("RUB", "250.75")])
async def test_owner_allocates_tjs_or_rub_with_ledger_audit_notification_and_realtime(
    client, make_account, db_session, conversion_rates, currency, amount
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    response = await client.post(
        f"/owner/accounts/{user.id}/fiat-wallets/allocate",
        json={
            "currency": currency,
            "amount": amount,
            "comment": "Managed allocation",
            "idempotency_key": f"allocate-{currency.lower()}-001",
        },
        headers=_headers(owner),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == currency
    assert Decimal(body["balance_after"]) == Decimal(amount)

    ledger = (
        await db_session.execute(
            select(FiatLedgerEntry).where(
                FiatLedgerEntry.reference_id == uuid.UUID(body["operation_id"])
            )
        )
    ).scalar_one()
    assert ledger.type == FiatLedgerEntryType.OWNER_ALLOCATION
    assert ledger.amount == Decimal(amount)
    assert ledger.balance_before == 0

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "fiat.allocate", AuditLog.entity_id == body["operation_id"]
            )
        )
    ).scalar_one()
    assert audit.audit_metadata["target_account_id"] == str(user.id)
    notification = (
        await db_session.execute(
            select(Notification).where(
                Notification.account_id == user.id,
                Notification.type == NotificationType.FIAT_BALANCE_UPDATED,
            )
        )
    ).scalar_one()
    assert notification.payload["currency"] == currency
    event = (
        await db_session.execute(
            select(RealtimeOutbox).where(RealtimeOutbox.entity_id == ledger.reference_id)
        )
    ).scalar_one()
    assert event.event == RealtimeEventName.FIAT_ALLOCATED.value
    assert set(event.recipient_account_ids) == {str(owner.id), str(user.id)}
    assert event.recipient_roles == []


async def test_allocation_is_idempotent_and_payload_mismatch_conflicts(
    client, make_account, db_session, conversion_rates
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    url = f"/owner/accounts/{user.id}/fiat-wallets/allocate"
    payload = {
        "currency": "TJS",
        "amount": "100",
        "idempotency_key": "same-allocation-key",
    }
    first = await client.post(url, json=payload, headers=_headers(owner))
    second = await client.post(url, json=payload, headers=_headers(owner))
    assert first.status_code == second.status_code == 200
    assert first.json()["operation_id"] == second.json()["operation_id"]
    mismatch = await client.post(
        url, json={**payload, "amount": "101"}, headers=_headers(owner)
    )
    assert mismatch.status_code == 409
    balance = await db_session.scalar(
        select(FiatWalletBalance.available).where(
            FiatWalletBalance.account_id == user.id,
            FiatWalletBalance.currency == Currency.TJS,
        )
    )
    assert balance == Decimal("100")
    assert await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "fiat.allocate")
    ) == 1


async def test_non_owner_cannot_allocate_or_convert(
    client, make_account, conversion_rates
):
    target = await make_account(role=UserRole.USER)
    user = await make_account(role=UserRole.USER)
    merchant = await make_account(role=UserRole.MERCHANT)
    allocation = {
        "currency": "TJS",
        "amount": "1",
        "idempotency_key": "forbidden-allocation",
    }
    conversion = {
        "from_currency": "TJS",
        "to_currency": "RUB",
        "source_amount": "1",
        "idempotency_key": "forbidden-conversion",
    }
    for actor in (user, merchant):
        assert (
            await client.post(
                f"/owner/accounts/{target.id}/fiat-wallets/allocate",
                json=allocation,
                headers=_headers(actor),
            )
        ).status_code == 403
        assert (
            await client.post(
                f"/owner/accounts/{target.id}/fiat-conversions",
                json=conversion,
                headers=_headers(actor),
            )
        ).status_code == 403


async def test_fiat_rbac_targets_currency_and_rate_outage_are_fail_safe(
    client, make_account, conversion_rates
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    merchant = await make_account(role=UserRole.MERCHANT)
    base = {"amount": "1", "idempotency_key": "validation-allocation"}
    assert (
        await client.post(
            f"/owner/accounts/{merchant.id}/fiat-wallets/allocate",
            json={**base, "currency": "TJS"},
            headers=_headers(owner),
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/owner/accounts/{user.id}/fiat-wallets/allocate",
            json={**base, "currency": "USDT"},
            headers=_headers(owner),
        )
    ).status_code == 400
    for amount in ("0", "-1"):
        assert (
            await client.post(
                f"/owner/accounts/{user.id}/fiat-wallets/allocate",
                json={**base, "currency": "TJS", "amount": amount},
                headers=_headers(owner),
            )
        ).status_code == 422
    assert (await client.get("/fiat-wallets", headers=_headers(merchant))).status_code == 403

    app.dependency_overrides[get_conversion_rate_dependency] = UnavailableConversionRates
    try:
        response = await client.post(
            "/owner/fiat-conversions/preview",
            json={"from_currency": "TJS", "to_currency": "RUB", "source_amount": "1"},
            headers=_headers(owner),
        )
        assert response.status_code == 503
    finally:
        app.dependency_overrides[get_conversion_rate_dependency] = lambda: conversion_rates


async def _allocate(client, owner, user, currency: str, amount: str, key: str):
    return await client.post(
        f"/owner/accounts/{user.id}/fiat-wallets/allocate",
        json={"currency": currency, "amount": amount, "idempotency_key": key},
        headers=_headers(owner),
    )


async def test_owner_previews_and_converts_tjs_to_rub_atomically(
    client, make_account, db_session, conversion_rates
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    assert (await _allocate(client, owner, user, "TJS", "1000", "seed-tjs-001")).status_code == 200

    preview = await client.post(
        "/owner/fiat-conversions/preview",
        json={"from_currency": "TJS", "to_currency": "RUB", "source_amount": "100"},
        headers=_headers(owner),
    )
    assert preview.status_code == 200
    assert Decimal(preview.json()["destination_amount"]) == Decimal("901.71325500")
    assert preview.json()["provider"] == "nbt"

    result = await client.post(
        f"/owner/accounts/{user.id}/fiat-conversions",
        json={
            "from_currency": "TJS",
            "to_currency": "RUB",
            "source_amount": "100",
            "comment": "Owner conversion",
            "idempotency_key": "convert-tjs-rub-001",
        },
        headers=_headers(owner),
    )
    assert result.status_code == 200
    body = result.json()
    assert Decimal(body["source_balance_after"]) == Decimal("900")
    assert Decimal(body["destination_balance_after"]) == Decimal("901.713255")
    assert body["rate_provider"] == "nbt"

    entries = (
        await db_session.execute(
            select(FiatLedgerEntry).where(
                FiatLedgerEntry.reference_id == uuid.UUID(body["id"])
            )
        )
    ).scalars().all()
    assert {item.type for item in entries} == {
        FiatLedgerEntryType.CONVERSION_DEBIT,
        FiatLedgerEntryType.CONVERSION_CREDIT,
    }
    tjs_amount = sum(
        (item.amount for item in entries if item.currency == Currency.TJS), Decimal()
    )
    assert tjs_amount == Decimal("-100")
    event = await db_session.scalar(
        select(RealtimeOutbox).where(RealtimeOutbox.entity_id == uuid.UUID(body["id"]))
    )
    assert event.event == RealtimeEventName.FIAT_CONVERTED.value
    assert set(event.recipient_account_ids) == {str(owner.id), str(user.id)}
    assert event.recipient_roles == []
    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "fiat.convert", AuditLog.entity_id == body["id"]
        )
    )
    assert audit.audit_metadata["rate_provider"] == "nbt"
    notifications = (
        await db_session.execute(
            select(Notification).where(
            Notification.account_id == user.id,
            Notification.type == NotificationType.FIAT_BALANCE_UPDATED,
            Notification.dedupe_hash.is_not(None),
            )
        )
    ).scalars().all()
    assert any(item.payload["currency"] == "RUB" for item in notifications)


async def test_owner_converts_rub_to_tjs_and_user_sees_read_only_history(
    client, make_account, conversion_rates
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await _allocate(client, owner, user, "RUB", "1000", "seed-rub-001")
    result = await client.post(
        f"/owner/accounts/{user.id}/fiat-conversions",
        json={
            "from_currency": "RUB",
            "to_currency": "TJS",
            "source_amount": "100",
            "idempotency_key": "convert-rub-tjs-001",
        },
        headers=_headers(owner),
    )
    assert result.status_code == 200
    assert Decimal(result.json()["destination_amount"]) == Decimal("11.09")
    history = await client.get("/fiat-wallets/conversions", headers=_headers(user))
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["id"] == result.json()["id"]


async def test_conversion_validation_insufficient_and_idempotent_retry(
    client, make_account, db_session, conversion_rates
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await _allocate(client, owner, user, "TJS", "100", "seed-validation")
    url = f"/owner/accounts/{user.id}/fiat-conversions"
    same = {
        "from_currency": "TJS",
        "to_currency": "TJS",
        "source_amount": "10",
        "idempotency_key": "same-currency-key",
    }
    assert (await client.post(url, json=same, headers=_headers(owner))).status_code == 400
    insufficient = {**same, "to_currency": "RUB", "source_amount": "101"}
    assert (
        await client.post(url, json=insufficient, headers=_headers(owner))
    ).status_code == 400
    assert (
        await client.post(
            url,
            json={**insufficient, "source_amount": "0"},
            headers=_headers(owner),
        )
    ).status_code == 422

    payload = {**insufficient, "source_amount": "10", "idempotency_key": "idem-convert-001"}
    first = await client.post(url, json=payload, headers=_headers(owner))
    second = await client.post(url, json=payload, headers=_headers(owner))
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert await db_session.scalar(select(func.count()).select_from(FiatConversion)) == 1
    assert await db_session.scalar(
        select(func.count()).select_from(FiatLedgerEntry).where(
            FiatLedgerEntry.type.in_(
                [FiatLedgerEntryType.CONVERSION_DEBIT, FiatLedgerEntryType.CONVERSION_CREDIT]
            )
        )
    ) == 2


async def test_conversion_history_snapshot_is_immutable_when_rate_changes(
    client, make_account, conversion_rates
):
    owner = await make_account(role=UserRole.OWNER)
    user = await make_account(role=UserRole.USER)
    await _allocate(client, owner, user, "TJS", "100", "seed-history")
    url = f"/owner/accounts/{user.id}/fiat-conversions"
    base = {"from_currency": "TJS", "to_currency": "RUB", "source_amount": "10"}
    first = await client.post(
        url, json={**base, "idempotency_key": "history-rate-x"}, headers=_headers(owner)
    )
    conversion_rates.rub_tjs = Decimal("0.125")
    second = await client.post(
        url, json={**base, "idempotency_key": "history-rate-y"}, headers=_headers(owner)
    )
    history = await client.get(
        f"/owner/fiat-conversions?account_id={user.id}", headers=_headers(owner)
    )
    by_id = {item["id"]: item for item in history.json()["items"]}
    assert by_id[first.json()["id"]]["exchange_rate"] == first.json()["exchange_rate"]
    assert first.json()["exchange_rate"] != second.json()["exchange_rate"]


async def test_managed_fiat_business_e2e_on_disposable_database(
    client, make_account, db_session, conversion_rates
):
    owner = await make_account(role=UserRole.OWNER)
    username = f"fiat_e2e_{uuid.uuid4().hex[:10]}"
    created = await client.post(
        "/owner/accounts",
        json={
            "username": username,
            "password": "DisposableFiatUser123",
            "role": "user",
            "full_name": "Disposable Fiat E2E",
            "email": None,
            "phone": None,
        },
        headers=_headers(owner),
    )
    assert created.status_code == 201
    user = await db_session.scalar(
        select(Account).where(Account.id == uuid.UUID(created.json()["id"]))
    )
    assert user is not None

    allocated = await _allocate(client, owner, user, "TJS", "1000", "e2e-allocate-tjs")
    assert allocated.status_code == 200
    preview = await client.post(
        "/owner/fiat-conversions/preview",
        json={"from_currency": "TJS", "to_currency": "RUB", "source_amount": "100"},
        headers=_headers(owner),
    )
    assert preview.status_code == 200
    forward = await client.post(
        f"/owner/accounts/{user.id}/fiat-conversions",
        json={
            "from_currency": "TJS",
            "to_currency": "RUB",
            "source_amount": "100",
            "idempotency_key": "e2e-forward-conversion",
        },
        headers=_headers(owner),
    )
    assert forward.status_code == 200
    reverse = await client.post(
        f"/owner/accounts/{user.id}/fiat-conversions",
        json={
            "from_currency": "RUB",
            "to_currency": "TJS",
            "source_amount": "50",
            "idempotency_key": "e2e-reverse-conversion",
        },
        headers=_headers(owner),
    )
    assert reverse.status_code == 200

    balances = await client.get("/fiat-wallets", headers=_headers(user))
    by_currency = {
        item["currency"]: Decimal(item["available"])
        for item in balances.json()["items"]
    }
    assert by_currency == {"TJS": Decimal("905.545"), "RUB": Decimal("851.713255")}
    history = await client.get("/fiat-wallets/conversions", headers=_headers(user))
    ledger = await client.get("/fiat-wallets/ledger", headers=_headers(user))
    assert history.json()["total"] == 2
    assert ledger.json()["total"] == 5
    assert (
        await client.post(
            f"/owner/accounts/{user.id}/fiat-conversions",
            json={
                "from_currency": "TJS",
                "to_currency": "RUB",
                "source_amount": "1",
                "idempotency_key": "e2e-user-forbidden",
            },
            headers=_headers(user),
        )
    ).status_code == 403
    assert await db_session.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action.in_(["fiat.allocate", "fiat.convert"])
        )
    ) == 3
    assert await db_session.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.account_id == user.id,
            Notification.type == NotificationType.FIAT_BALANCE_UPDATED,
        )
    ) == 3
