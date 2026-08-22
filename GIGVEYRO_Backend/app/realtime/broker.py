import asyncio
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

from fastapi import WebSocket

from app.enums.account import UserRole
from app.realtime.contracts import RealtimeEvent


class RealtimeBroker(Protocol):
    async def connect(
        self, account_id: uuid.UUID, role: UserRole, websocket: WebSocket
    ) -> uuid.UUID: ...

    async def disconnect(self, connection_id: uuid.UUID) -> None: ...

    async def send_to_account(self, account_id: uuid.UUID, event: RealtimeEvent) -> int: ...

    async def send_to_role(self, role: UserRole, event: RealtimeEvent) -> int: ...

    async def broadcast(self, event: RealtimeEvent) -> int: ...

    async def publish(
        self,
        event: RealtimeEvent,
        *,
        account_ids: set[uuid.UUID],
        roles: set[UserRole],
    ) -> int: ...


@dataclass(frozen=True)
class _Connection:
    id: uuid.UUID
    account_id: uuid.UUID
    role: UserRole
    websocket: WebSocket


class InMemoryRealtimeBroker:
    """Single-process broker. The protocol boundary allows a Redis-backed broker later."""

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, _Connection] = {}
        self._accounts: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        self._roles: dict[UserRole, set[uuid.UUID]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(
        self, account_id: uuid.UUID, role: UserRole, websocket: WebSocket
    ) -> uuid.UUID:
        connection = _Connection(uuid.uuid4(), account_id, role, websocket)
        await websocket.accept(subprotocol="gigveyro.realtime.v1")
        async with self._lock:
            self._connections[connection.id] = connection
            self._accounts[account_id].add(connection.id)
            self._roles[role].add(connection.id)
        return connection.id

    async def disconnect(self, connection_id: uuid.UUID) -> None:
        async with self._lock:
            connection = self._connections.pop(connection_id, None)
            if connection is None:
                return
            self._accounts[connection.account_id].discard(connection_id)
            self._roles[connection.role].discard(connection_id)
            if not self._accounts[connection.account_id]:
                self._accounts.pop(connection.account_id, None)
            if not self._roles[connection.role]:
                self._roles.pop(connection.role, None)

    async def send_to_account(self, account_id: uuid.UUID, event: RealtimeEvent) -> int:
        return await self._send_ids(await self._ids_for_account(account_id), event)

    async def send_to_role(self, role: UserRole, event: RealtimeEvent) -> int:
        return await self._send_ids(await self._ids_for_role(role), event)

    async def broadcast(self, event: RealtimeEvent) -> int:
        async with self._lock:
            connection_ids = set(self._connections)
        return await self._send_ids(connection_ids, event)

    async def publish(
        self,
        event: RealtimeEvent,
        *,
        account_ids: set[uuid.UUID],
        roles: set[UserRole],
    ) -> int:
        connection_ids: set[uuid.UUID] = set()
        async with self._lock:
            for account_id in account_ids:
                connection_ids.update(self._accounts.get(account_id, set()))
            for role in roles:
                connection_ids.update(self._roles.get(role, set()))
        return await self._send_ids(connection_ids, event)

    async def connection_count(self, account_id: uuid.UUID | None = None) -> int:
        async with self._lock:
            if account_id:
                return len(self._accounts.get(account_id, set()))
            return len(self._connections)

    async def _ids_for_account(self, account_id: uuid.UUID) -> set[uuid.UUID]:
        async with self._lock:
            return set(self._accounts.get(account_id, set()))

    async def _ids_for_role(self, role: UserRole) -> set[uuid.UUID]:
        async with self._lock:
            return set(self._roles.get(role, set()))

    async def _send_ids(self, connection_ids: set[uuid.UUID], event: RealtimeEvent) -> int:
        async with self._lock:
            connections = [
                self._connections[connection_id]
                for connection_id in connection_ids
                if connection_id in self._connections
            ]
        delivered = 0
        payload = event.model_dump(mode="json")
        for connection in connections:
            try:
                await connection.websocket.send_json(payload)
                delivered += 1
            except Exception:
                await self.disconnect(connection.id)
        return delivered


class RedisRealtimeBroker:
    """Redis Pub/Sub backed broker for horizontal multi-process scaling."""

    def __init__(self) -> None:
        self._connections: dict[uuid.UUID, _Connection] = {}
        self._accounts: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
        self._roles: dict[UserRole, set[uuid.UUID]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._listener_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._ready_event = asyncio.Event()

    async def startup(self) -> None:
        """Start background pub/sub listener task."""
        if self._listener_task is not None and not self._listener_task.done():
            return
        self._stop_event.clear()
        self._ready_event.clear()
        self._listener_task = asyncio.create_task(self._listen_loop())
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=5)
        except TimeoutError as exc:
            await self.shutdown()
            raise RuntimeError("Redis realtime subscription did not become ready") from exc

    async def shutdown(self) -> None:
        """Stop background pub/sub listener task."""
        self._stop_event.set()
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None
        self._ready_event.clear()

    async def _listen_loop(self) -> None:
        """Background listener loop subscribing to Redis channel."""
        import json
        import logging

        from redis.exceptions import RedisError

        from app.core.config import settings
        from app.infra.redis_client import get_redis

        logger = logging.getLogger(__name__)
        channel_name = f"{settings.REDIS_KEY_PREFIX}:realtime_events"

        while not self._stop_event.is_set():
            try:
                client = get_redis()
                pubsub = client.pubsub()
                async with pubsub as ps:
                    await ps.subscribe(channel_name)
                    self._ready_event.set()
                    logger.debug("Subscribed to Redis channel: %s", channel_name)

                    while not self._stop_event.is_set():
                        msg = await ps.get_message(ignore_subscribe_messages=True, timeout=1.0)
                        if msg is None:
                            continue

                        data_str = msg.get("data")
                        if not data_str:
                            continue

                        try:
                            data = json.loads(data_str)
                            event_data = data.get("event")
                            recipient_account_ids = data.get("account_ids")
                            recipient_roles = data.get("roles")
                            is_broadcast = data.get("broadcast", False)

                            event = RealtimeEvent.model_validate(event_data)

                            await self._deliver_locally(
                                event=event,
                                account_ids={
                                    uuid.UUID(uid) for uid in (recipient_account_ids or [])
                                },
                                roles={UserRole(role) for role in (recipient_roles or [])},
                                broadcast=is_broadcast,
                            )
                        except Exception as exc:
                            logger.error("Failed to parse pubsub message: %s", exc)
            except RedisError as exc:
                self._ready_event.clear()
                logger.warning("Redis pub/sub disconnect: %s. Reconnecting in 5s...", exc)
                await asyncio.sleep(5)
            except Exception as exc:
                self._ready_event.clear()
                logger.error("Unexpected error in pub/sub listener loop: %s", exc)
                await asyncio.sleep(5)

    async def _deliver_locally(
        self,
        event: RealtimeEvent,
        account_ids: set[uuid.UUID],
        roles: set[UserRole],
        broadcast: bool = False,
    ) -> None:
        """Delivers a published event to local connections matching target criteria."""
        connection_ids: set[uuid.UUID] = set()
        async with self._lock:
            if broadcast:
                connection_ids.update(self._connections.keys())
            else:
                for account_id in account_ids:
                    connection_ids.update(self._accounts.get(account_id, set()))
                for role in roles:
                    connection_ids.update(self._roles.get(role, set()))

            connections = [
                self._connections[connection_id]
                for connection_id in connection_ids
                if connection_id in self._connections
            ]

        payload = event.model_dump(mode="json")
        for connection in connections:
            try:
                await connection.websocket.send_json(payload)
            except Exception:
                await self.disconnect(connection.id)

    async def connect(
        self, account_id: uuid.UUID, role: UserRole, websocket: WebSocket
    ) -> uuid.UUID:
        connection = _Connection(uuid.uuid4(), account_id, role, websocket)
        await websocket.accept(subprotocol="gigveyro.realtime.v1")
        async with self._lock:
            self._connections[connection.id] = connection
            self._accounts[account_id].add(connection.id)
            self._roles[role].add(connection.id)
        return connection.id

    async def disconnect(self, connection_id: uuid.UUID) -> None:
        async with self._lock:
            connection = self._connections.pop(connection_id, None)
            if connection is None:
                return
            self._accounts[connection.account_id].discard(connection_id)
            self._roles[connection.role].discard(connection_id)
            if not self._accounts[connection.account_id]:
                self._accounts.pop(connection.account_id, None)
            if not self._roles[connection.role]:
                self._roles.pop(connection.role, None)

    async def publish(
        self,
        event: RealtimeEvent,
        *,
        account_ids: set[uuid.UUID],
        roles: set[UserRole],
    ) -> int:
        import json

        from app.core.config import settings
        from app.infra.redis_client import get_redis

        channel_name = f"{settings.REDIS_KEY_PREFIX}:realtime_events"
        payload = {
            "event": event.model_dump(mode="json"),
            "account_ids": [str(uid) for uid in account_ids],
            "roles": [role.value for role in roles],
            "broadcast": False,
        }
        client = get_redis()
        return await client.publish(channel_name, json.dumps(payload))

    async def send_to_account(self, account_id: uuid.UUID, event: RealtimeEvent) -> int:
        return await self.publish(event, account_ids={account_id}, roles=set())

    async def send_to_role(self, role: UserRole, event: RealtimeEvent) -> int:
        return await self.publish(event, account_ids=set(), roles={role})

    async def broadcast(self, event: RealtimeEvent) -> int:
        import json

        from app.core.config import settings
        from app.infra.redis_client import get_redis

        channel_name = f"{settings.REDIS_KEY_PREFIX}:realtime_events"
        payload = {
            "event": event.model_dump(mode="json"),
            "account_ids": [],
            "roles": [],
            "broadcast": True,
        }
        client = get_redis()
        return await client.publish(channel_name, json.dumps(payload))
