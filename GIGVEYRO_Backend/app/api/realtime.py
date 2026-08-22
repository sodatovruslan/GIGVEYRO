import asyncio
import uuid

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_account
from app.core.config import settings
from app.core.security import TokenError, TokenType, create_realtime_ticket, decode_token
from app.db.session import get_db
from app.models.account import Account
from app.realtime.runtime import realtime_broker
from app.repositories.account import AccountRepository
from app.schemas.realtime import RealtimeTicketResponse

router = APIRouter(tags=["Realtime"])
_PROTOCOL = "gigveyro.realtime.v1"
_TICKET_PREFIX = "gigveyro.ticket."


@router.post("/api/v1/realtime/ticket", response_model=RealtimeTicketResponse)
async def issue_realtime_ticket(
    account: Account = Depends(get_current_account),
) -> RealtimeTicketResponse:
    return RealtimeTicketResponse(
        ticket=create_realtime_ticket(
            account.id,
            account.role.value,
            settings.REALTIME_TICKET_EXPIRE_SECONDS,
        ),
        expires_in=settings.REALTIME_TICKET_EXPIRE_SECONDS,
    )


def _ticket_from_protocols(websocket: WebSocket) -> str | None:
    protocols = {
        value.strip()
        for value in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if value.strip()
    }
    if _PROTOCOL not in protocols:
        return None
    encoded = next((value for value in protocols if value.startswith(_TICKET_PREFIX)), None)
    return encoded.removeprefix(_TICKET_PREFIX) if encoded else None


async def _authenticate(websocket: WebSocket, db: AsyncSession) -> Account | None:
    origin = websocket.headers.get("origin")
    if not origin or origin not in settings.CORS_ALLOWED_ORIGINS:
        return None
    ticket = _ticket_from_protocols(websocket)
    if not ticket:
        return None
    try:
        payload = decode_token(ticket, TokenType.REALTIME)
        account_id = uuid.UUID(payload["sub"])
    except (TokenError, ValueError, KeyError):
        return None
    account = await AccountRepository(db).get_by_id(account_id)
    if account is None or not account.is_active or payload.get("role") != account.role.value:
        return None
    return account


@router.websocket("/api/v1/ws")
async def realtime_websocket(websocket: WebSocket, db: AsyncSession = Depends(get_db)) -> None:
    account = await _authenticate(websocket, db)
    if account is None:
        await websocket.close(code=4401, reason="authentication required")
        return

    connection_id = await realtime_broker.connect(account.id, account.role, websocket)
    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_json(), timeout=settings.REALTIME_HEARTBEAT_SECONDS
                )
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(), timeout=settings.REALTIME_HEARTBEAT_SECONDS
                    )
                except TimeoutError:
                    await websocket.close(code=1001, reason="heartbeat timeout")
                    break
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif message.get("type") != "pong":
                await websocket.close(code=1003, reason="unsupported client message")
                break
    except WebSocketDisconnect:
        pass
    finally:
        await realtime_broker.disconnect(connection_id)
