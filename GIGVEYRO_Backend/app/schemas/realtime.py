from pydantic import BaseModel


class RealtimeTicketResponse(BaseModel):
    ticket: str
    expires_in: int
    websocket_path: str = "/api/v1/ws"
