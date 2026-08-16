import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict

from app.enums.notification import NotificationChannel, NotificationStatus, NotificationType


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    type: NotificationType
    channel: NotificationChannel
    title: str
    message: str
    payload: dict[str, Any] | None = None
    status: NotificationStatus
    is_read: bool
    created_at: datetime
    sent_at: datetime | None = None


class TelegramLinkCodeRead(BaseModel):
    link_code: str
    expires_at: datetime
    bot_username: str = "GigveyroBot"


class TelegramWebhookPayload(BaseModel):
    update_id: int
    message: dict[str, Any] | None = None
