import logging

from app.enums.account import UserRole
from app.enums.notification import NotificationMessageKey, NotificationType
from app.models.access_request import AccessRequest
from app.repositories.access_request import AccessRequestRepository
from app.repositories.account import AccountRepository
from app.services.notification import NotificationService

logger = logging.getLogger(__name__)


class AccessRequestService:
    """Persists a visitor's "I want an account" submission and alerts the
    Owner. Never creates an Account - public registration stays disabled."""

    def __init__(
        self,
        requests: AccessRequestRepository,
        accounts: AccountRepository,
        notifications: NotificationService,
    ):
        self.requests = requests
        self.accounts = accounts
        self.notifications = notifications

    async def submit(
        self,
        *,
        full_name: str,
        contact: str,
        note: str | None,
        client_ip: str | None,
    ) -> AccessRequest:
        request = await self.requests.create(
            AccessRequest(
                full_name=full_name,
                contact=contact,
                note=note,
                client_ip=client_ip,
            )
        )

        owner = await self.accounts.get_by_role(UserRole.OWNER)
        if owner is None:
            logger.warning("event=access_request.no_owner_account request_id=%s", request.id)
            return request

        await self.notifications.emit_semantic_notification(
            owner.id,
            NotificationType.ACCESS_REQUEST_SUBMITTED,
            NotificationMessageKey.ACCESS_REQUEST_SUBMITTED,
            {"full_name": full_name, "contact": contact, "note": note or "—"},
            payload={"access_request_id": str(request.id)},
            dedupe_key=f"access_request:{request.id}",
        )
        return request
