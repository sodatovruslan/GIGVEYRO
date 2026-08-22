import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from starlette.datastructures import Headers

from app.api.realtime import _authenticate
from app.core.config import settings
from app.core.security import (
    TokenError,
    TokenType,
    create_access_token,
    create_realtime_ticket,
    decode_token,
)
from app.enums.account import UserRole
from app.enums.deal import DealStatus
from app.models.deal import Deal
from app.models.realtime import RealtimeOutbox
from app.realtime.broker import InMemoryRealtimeBroker
from app.realtime.contracts import RealtimeEvent, RealtimeEventName
from app.repositories.realtime import RealtimeOutboxRepository
from app.services.realtime import RealtimeEventService, RealtimeOutboxDispatcher


class FakeWebSocket:
    def __init__(self, headers: dict[str, str] | None = None, *, fail_send: bool = False):
        self.headers = Headers(headers or {})
        self.fail_send = fail_send
        self.accepted_subprotocol: str | None = None
        self.messages: list[dict[str, object]] = []

    async def accept(self, subprotocol: str | None = None) -> None:
        self.accepted_subprotocol = subprotocol

    async def send_json(self, payload: dict[str, object]) -> None:
        if self.fail_send:
            raise RuntimeError("connection closed")
        self.messages.append(payload)


def _event() -> RealtimeEvent:
    return RealtimeEvent(
        id=uuid.uuid4(),
        event=RealtimeEventName.DEAL_ACCEPTED,
        entity_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        data={"status": "accepted"},
    )


def _auth(account) -> dict[str, str]:
    token = create_access_token(account.id, account.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _event_names(db_session, deal_id: uuid.UUID) -> list[str]:
    result = await db_session.execute(
        select(RealtimeOutbox.event)
        .where(RealtimeOutbox.entity_id == deal_id)
        .order_by(RealtimeOutbox.occurred_at)
    )
    return list(result.scalars().all())


async def test_realtime_ticket_requires_authentication(client):
    response = await client.post("/api/v1/realtime/ticket")

    assert response.status_code == 401


@pytest.mark.parametrize("role", list(UserRole))
async def test_realtime_ticket_is_short_lived_and_role_scoped(client, make_account, role):
    account = await make_account(role=role)
    access_token = create_access_token(account.id, role.value)

    response = await client.post(
        "/api/v1/realtime/ticket",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    claims = decode_token(payload["ticket"], TokenType.REALTIME)
    assert claims["sub"] == str(account.id)
    assert claims["role"] == role.value
    assert payload["expires_in"] == settings.REALTIME_TICKET_EXPIRE_SECONDS
    assert payload["websocket_path"] == "/api/v1/ws"
    with pytest.raises(TokenError):
        decode_token(payload["ticket"], TokenType.ACCESS)


async def test_websocket_auth_rejects_access_token(db_session, make_account):
    account = await make_account()
    websocket = FakeWebSocket(
        {
            "origin": settings.CORS_ALLOWED_ORIGINS[0],
            "sec-websocket-protocol": (
                "gigveyro.realtime.v1, "
                f"gigveyro.ticket.{create_access_token(account.id, account.role.value)}"
            ),
        }
    )

    assert await _authenticate(websocket, db_session) is None  # type: ignore[arg-type]


async def test_websocket_auth_rejects_expired_realtime_ticket(db_session, make_account):
    account = await make_account()
    ticket = create_realtime_ticket(account.id, account.role.value, expires_seconds=-1)
    websocket = FakeWebSocket(
        {
            "origin": settings.CORS_ALLOWED_ORIGINS[0],
            "sec-websocket-protocol": (f"gigveyro.realtime.v1, gigveyro.ticket.{ticket}"),
        }
    )

    assert await _authenticate(websocket, db_session) is None  # type: ignore[arg-type]


async def test_broker_routes_privately_and_supports_multiple_tabs():
    broker = InMemoryRealtimeBroker()
    user_id = uuid.uuid4()
    merchant_id = uuid.uuid4()
    other_merchant_id = uuid.uuid4()
    user_tab_one = FakeWebSocket()
    user_tab_two = FakeWebSocket()
    merchant = FakeWebSocket()
    other_merchant = FakeWebSocket()
    owner = FakeWebSocket()

    connections = [
        await broker.connect(user_id, UserRole.USER, user_tab_one),  # type: ignore[arg-type]
        await broker.connect(user_id, UserRole.USER, user_tab_two),  # type: ignore[arg-type]
        await broker.connect(merchant_id, UserRole.MERCHANT, merchant),  # type: ignore[arg-type]
        await broker.connect(  # type: ignore[arg-type]
            other_merchant_id, UserRole.MERCHANT, other_merchant
        ),
        await broker.connect(uuid.uuid4(), UserRole.OWNER, owner),  # type: ignore[arg-type]
    ]

    delivered = await broker.publish(
        _event(),
        account_ids={user_id, merchant_id},
        roles={UserRole.OWNER},
    )

    assert delivered == 4
    assert len(user_tab_one.messages) == len(user_tab_two.messages) == 1
    assert len(merchant.messages) == len(owner.messages) == 1
    assert other_merchant.messages == []
    assert user_tab_one.accepted_subprotocol == "gigveyro.realtime.v1"

    for connection_id in connections:
        await broker.disconnect(connection_id)
    assert await broker.connection_count() == 0


async def test_broker_removes_failed_connections():
    broker = InMemoryRealtimeBroker()
    account_id = uuid.uuid4()
    websocket = FakeWebSocket(fail_send=True)
    await broker.connect(account_id, UserRole.USER, websocket)  # type: ignore[arg-type]

    delivered = await broker.send_to_account(account_id, _event())

    assert delivered == 0
    assert await broker.connection_count(account_id) == 0


async def test_deal_creation_enqueues_transactional_event(client, db_session, make_account):
    merchant = await make_account(role=UserRole.MERCHANT)

    response = await client.post(
        "/merchant/deals",
        json={"amount_tjs": "200"},
        headers=_auth(merchant),
    )

    assert response.status_code == 201
    deal_id = uuid.UUID(response.json()["id"])
    entry = (
        await db_session.execute(select(RealtimeOutbox).where(RealtimeOutbox.entity_id == deal_id))
    ).scalar_one()
    assert entry.event == RealtimeEventName.DEAL_CREATED.value
    assert entry.recipient_account_ids == [str(merchant.id)]
    assert set(entry.recipient_roles) == {UserRole.OWNER.value, UserRole.USER.value}
    assert entry.data == {"status": "available"}


async def test_accept_and_lazy_expiry_enqueue_events(
    client,
    db_session,
    make_account,
    make_wallet,
    make_requisite,
    make_traffic_settings,
    make_deal,
):
    merchant = await make_account(role=UserRole.MERCHANT)
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, available=Decimal("500"))
    requisite = await make_requisite(user)
    await make_traffic_settings(user, is_enabled=True)
    accepted = await make_deal(merchant)
    expired = await make_deal(merchant, expires_in_minutes=-1)

    accept_response = await client.post(
        f"/deals/{accepted.id}/accept",
        json={"payment_requisite_id": str(requisite.id)},
        headers=_auth(user),
    )
    list_response = await client.get("/deals/available", headers=_auth(user))

    assert accept_response.status_code == 200
    assert list_response.status_code == 200
    assert await _event_names(db_session, accepted.id) == [RealtimeEventName.DEAL_ACCEPTED.value]
    assert await _event_names(db_session, expired.id) == [RealtimeEventName.DEAL_EXPIRED.value]


@pytest.mark.parametrize(
    ("action", "expected_event"),
    [
        ("complete", RealtimeEventName.DEAL_COMPLETED),
        ("release", RealtimeEventName.DEAL_RELEASED),
    ],
)
async def test_owner_settlement_enqueues_terminal_event(
    client,
    db_session,
    make_account,
    make_wallet,
    make_merchant_wallet,
    make_deal,
    action,
    expected_event,
):
    owner = await make_account(role=UserRole.OWNER)
    merchant = await make_account(role=UserRole.MERCHANT)
    await make_merchant_wallet(merchant, available=Decimal("100"))
    user = await make_account(role=UserRole.USER)
    await make_wallet(user, frozen=Decimal("50"))
    deal = await make_deal(
        merchant,
        status=DealStatus.ACCEPTED,
        user=user,
        amount_usdt=Decimal("20"),
    )

    response = await client.post(f"/owner/deals/{deal.id}/{action}", headers=_auth(owner))

    assert response.status_code == 200
    assert await _event_names(db_session, deal.id) == [expected_event.value]


async def test_appeal_open_enqueues_disputed_event(client, db_session, make_account, make_deal):
    merchant = await make_account(role=UserRole.MERCHANT)
    user = await make_account(role=UserRole.USER)
    deal = await make_deal(
        merchant,
        status=DealStatus.ACCEPTED,
        user=user,
        amount_usdt=Decimal("20"),
    )

    response = await client.post(
        f"/appeals/deals/{deal.id}/appeal",
        json={"reason_code": "payment_not_received", "message": "Payment was not received"},
        headers=_auth(user),
    )

    assert response.status_code == 201
    assert await _event_names(db_session, deal.id) == [RealtimeEventName.DEAL_DISPUTED.value]


async def test_realtime_outbox_rolls_back_with_business_transaction(
    db_session, make_account, make_deal
):
    merchant = await make_account(role=UserRole.MERCHANT)
    deal: Deal = await make_deal(merchant)
    nested = await db_session.begin_nested()
    entry = await RealtimeEventService(RealtimeOutboxRepository(db_session)).enqueue_deal(
        RealtimeEventName.DEAL_CREATED, deal
    )
    entry_id = entry.id

    await nested.rollback()

    assert await db_session.get(RealtimeOutbox, entry_id) is None
    assert await db_session.get(Deal, deal.id) is not None


async def test_delivery_failure_does_not_rollback_financial_state(
    db_session, make_account, make_deal
):
    class FailingBroker:
        async def publish(self, *args, **kwargs):
            raise RuntimeError("broker unavailable")

    merchant = await make_account(role=UserRole.MERCHANT)
    deal: Deal = await make_deal(merchant)
    entry = await RealtimeEventService(RealtimeOutboxRepository(db_session)).enqueue_deal(
        RealtimeEventName.DEAL_CREATED, deal
    )

    processed = await RealtimeOutboxDispatcher(FailingBroker()).process_batch(db_session)  # type: ignore[arg-type]

    assert processed == 0
    assert entry.processed_at is None
    assert entry.attempts == 1
    assert entry.last_error == "broker unavailable"
    assert await db_session.get(Deal, deal.id) is not None
