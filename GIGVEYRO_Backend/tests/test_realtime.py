import uuid
from datetime import UTC, datetime

import pytest
from starlette.datastructures import Headers

from app.api.realtime import _authenticate
from app.core.config import settings
from app.core.security import TokenError, TokenType, create_access_token, decode_token
from app.enums.account import UserRole
from app.realtime.broker import InMemoryRealtimeBroker
from app.realtime.contracts import RealtimeEvent, RealtimeEventName


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
