import asyncio
import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.enums.account import UserRole
from app.realtime.broker import RedisRealtimeBroker
from app.realtime.contracts import RealtimeEvent, RealtimeEventName
from tests.test_realtime import FakeWebSocket


def _event() -> RealtimeEvent:
    return RealtimeEvent(
        id=uuid.uuid4(),
        event=RealtimeEventName.DEAL_ACCEPTED,
        entity_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
        data={"status": "accepted"},
    )


@pytest.mark.asyncio
async def test_redis_broker_mock_pubsub_delivery():
    """Verify Redis Pub/Sub messages reach matching local sockets."""

    broker = RedisRealtimeBroker()
    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
    mock_pubsub.__aenter__.return_value = mock_pubsub

    user_id = uuid.uuid4()
    socket = FakeWebSocket()

    # Connect client locally
    connection_id = await broker.connect(user_id, UserRole.USER, socket)
    assert broker._deliver_locally is not None

    # Prepare mock event and Pub/Sub payload
    event = _event()
    channel_msg = {
        "type": "message",
        "pattern": None,
        "channel": b"gigveyro:test:realtime_events",
        "data": json.dumps(
            {
                "event": event.model_dump(mode="json"),
                "account_ids": [str(user_id)],
                "roles": [],
                "broadcast": False,
            }
        ),
    }

    # Queue of messages to return from get_message
    msg_queue = [channel_msg, None]

    async def get_message_mock(*args, **kwargs):
        if msg_queue:
            return msg_queue.pop(0)
        # Block to simulate idle loop
        await asyncio.sleep(5)
        return None

    mock_pubsub.get_message.side_effect = get_message_mock

    # Run broker loop with mocked get_redis
    with patch("app.infra.redis_client.get_redis", return_value=mock_redis):
        await broker.startup()
        # Allow the background task to run one iteration
        await asyncio.sleep(0.1)
        await broker.shutdown()

    # Verify message was delivered to the socket
    assert len(socket.messages) == 1
    assert socket.messages[0]["id"] == str(event.id)

    # Disconnect client
    await broker.disconnect(connection_id)


@pytest.mark.asyncio
async def test_redis_broker_publish_calls_redis():
    """Verify that publish() posts correct JSON payload to the namespace channel."""
    broker = RedisRealtimeBroker()
    mock_redis = AsyncMock()

    event = _event()
    user_id = uuid.uuid4()

    with patch("app.infra.redis_client.get_redis", return_value=mock_redis):
        await broker.publish(event, account_ids={user_id}, roles={UserRole.OWNER})

    mock_redis.publish.assert_called_once()
    channel, payload_str = mock_redis.publish.call_args[0]

    # Verify channel namespace has suffix and prefix
    assert channel.startswith(settings.REDIS_KEY_PREFIX)
    assert channel.endswith("realtime_events")

    # Verify payload format
    payload = json.loads(payload_str)
    assert payload["event"]["id"] == str(event.id)
    assert payload["account_ids"] == [str(user_id)]
    assert payload["roles"] == [UserRole.OWNER.value]
    assert payload["broadcast"] is False


@pytest.mark.asyncio
async def test_redis_broker_broadcast_calls_redis():
    """Verify that broadcast() posts a broadcast payload to Redis."""
    broker = RedisRealtimeBroker()
    mock_redis = AsyncMock()

    event = _event()

    with patch("app.infra.redis_client.get_redis", return_value=mock_redis):
        await broker.broadcast(event)

    mock_redis.publish.assert_called_once()
    channel, payload_str = mock_redis.publish.call_args[0]

    payload = json.loads(payload_str)
    assert payload["broadcast"] is True
    assert payload["account_ids"] == []
    assert payload["roles"] == []


@pytest.mark.asyncio
async def test_redis_broker_ignores_malformed_json():
    """Verify that listener loop doesn't crash on malformed JSON payload."""

    broker = RedisRealtimeBroker()
    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
    mock_pubsub.__aenter__.return_value = mock_pubsub

    # Malformed JSON payload
    channel_msg = {
        "type": "message",
        "pattern": None,
        "channel": b"gigveyro:test:realtime_events",
        "data": "{invalid-json}",
    }

    msg_queue = [channel_msg, None]

    async def get_message_mock(*args, **kwargs):
        if msg_queue:
            return msg_queue.pop(0)
        await asyncio.sleep(5)
        return None

    mock_pubsub.get_message.side_effect = get_message_mock

    with patch("app.infra.redis_client.get_redis", return_value=mock_redis):
        await broker.startup()
        await asyncio.sleep(0.1)
        await broker.shutdown()

    # The loop should not crash and terminate cleanly.
    assert broker._listener_task is None
