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
