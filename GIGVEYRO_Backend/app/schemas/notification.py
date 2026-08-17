import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.enums.notification import NotificationChannel, NotificationStatus, NotificationType


class NotificationPreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    account_id: uuid.UUID
    in_app_enabled: bool
    telegram_enabled: bool
    deal_notifications: bool
    deposit_notifications: bool
    appeal_notifications: bool
    withdrawal_notifications: bool


class NotificationPreferenceUpdate(BaseModel):
    in_app_enabled: bool | None = None
    telegram_enabled: bool | None = None
    deal_notifications: bool | None = None
    deposit_notifications: bool | None = None
    appeal_notifications: bool | None = None
    withdrawal_notifications: bool | None = None


class NotificationDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    notification_id: uuid.UUID
    channel: NotificationChannel
    status: NotificationStatus
    attempts: int
    last_error: str | None = None
    sent_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    type: NotificationType
    title: str
    message: str
    payload: dict[str, Any] | None = None
    is_read: bool
    created_at: datetime
    deliveries: list[NotificationDeliveryRead] = Field(default_factory=list)


class UnreadCountRead(BaseModel):
    unread_count: int


class TelegramLinkCodeRead(BaseModel):
    verification_code: str
    expires_at: datetime
    bot_username: str = "GigveyroBot"


class TelegramWebhookPayload(BaseModel):
    update_id: int
    message: dict[str, Any] | None = None
