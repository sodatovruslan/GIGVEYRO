from sqlalchemy import select

from app.core.config import settings
from app.enums.account import UserRole
from app.enums.notification import NotificationStatus
from app.models.access_request import AccessRequest
from app.models.account import Account
from app.models.notification import Notification, NotificationOutbox, NotificationPreference

VALID_PAYLOAD = {
    "full_name": "Иван Тестов",
    "contact": "@ivan_test",
    "note": "Хочу зарегистрироваться как продавец",
}


async def _make_owner_with_telegram_enabled(make_account, db_session) -> Account:
    owner = await make_account(role=UserRole.OWNER)
    db_session.add(NotificationPreference(account_id=owner.id, telegram_enabled=True))
    await db_session.flush()
    return owner


async def test_create_access_request_succeeds_without_auth(client):
    response = await client.post("/access-requests", json=VALID_PAYLOAD)

    assert response.status_code == 200
    assert response.json() == {"status": "received"}


async def test_create_access_request_persists_row(client, db_session):
    response = await client.post("/access-requests", json=VALID_PAYLOAD)
    assert response.status_code == 200

    result = await db_session.execute(select(AccessRequest))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].full_name == "Иван Тестов"
    assert rows[0].contact == "@ivan_test"
    assert rows[0].note == "Хочу зарегистрироваться как продавец"


async def test_create_access_request_notifies_owner(
    client, make_account, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "TELEGRAM_DELIVERY_ENABLED", True)
    owner = await _make_owner_with_telegram_enabled(make_account, db_session)

    response = await client.post("/access-requests", json=VALID_PAYLOAD)
    assert response.status_code == 200

    notif_result = await db_session.execute(
        select(Notification).where(Notification.account_id == owner.id)
    )
    notification = notif_result.scalar_one()
    assert notification.message_key == "access_request.submitted"
    assert notification.message_params == {
        "full_name": "Иван Тестов",
        "contact": "@ivan_test",
        "note": "Хочу зарегистрироваться как продавец",
    }

    outbox_result = await db_session.execute(
        select(NotificationOutbox).where(NotificationOutbox.account_id == owner.id)
    )
    outbox_entry = outbox_result.scalar_one()
    assert outbox_entry.status == NotificationStatus.PENDING


async def test_create_access_request_without_note_uses_placeholder(
    client, make_account, db_session
):
    owner = await _make_owner_with_telegram_enabled(make_account, db_session)

    response = await client.post(
        "/access-requests", json={"full_name": "Без заметки", "contact": "+992000000000"}
    )
    assert response.status_code == 200

    notif_result = await db_session.execute(
        select(Notification).where(Notification.account_id == owner.id)
    )
    notification = notif_result.scalar_one()
    assert notification.message_params["note"] == "—"


async def test_create_access_request_without_owner_still_succeeds(client, db_session):
    """No Owner account exists yet - the visitor still gets a clean ack and
    the request is still recorded for later manual follow-up."""
    response = await client.post("/access-requests", json=VALID_PAYLOAD)

    assert response.status_code == 200
    result = await db_session.execute(select(AccessRequest))
    assert len(result.scalars().all()) == 1


async def test_create_access_request_never_creates_an_account(client, db_session):
    before = (await db_session.execute(select(Account))).scalars().all()

    response = await client.post("/access-requests", json=VALID_PAYLOAD)
    assert response.status_code == 200

    after = (await db_session.execute(select(Account))).scalars().all()
    assert len(after) == len(before)


async def test_create_access_request_rejects_blank_fields(client):
    response = await client.post(
        "/access-requests", json={"full_name": "   ", "contact": "@someone"}
    )
    assert response.status_code == 422


async def test_create_access_request_requires_full_name_and_contact(client):
    response = await client.post("/access-requests", json={"full_name": "Only Name"})
    assert response.status_code == 422


async def test_create_access_request_rejects_oversized_note(client):
    response = await client.post(
        "/access-requests",
        json={"full_name": "Name", "contact": "@x", "note": "a" * 501},
    )
    assert response.status_code == 422


async def test_public_registration_routes_still_absent(client):
    """This new endpoint must not become a backdoor into public registration -
    it only ever writes an AccessRequest row, never an Account."""
    from app.main import app

    route_paths = {route.path for route in app.routes}
    assert "/register" not in route_paths
    assert "/access-requests" in route_paths
