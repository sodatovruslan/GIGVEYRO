import uuid

from sqlalchemy import delete, select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.enums.notification import NotificationStatus, NotificationType
from app.models.account import Account
from app.models.notification import NotificationOutbox
from app.repositories.notification import NotificationRepository
from app.repositories.telegram import TelegramLinkRepository
from app.services.notification import NotificationService
from app.services.telegram import TelegramService
from app.services.telegram_provider import MockTelegramProvider
from app.workers.jobs.notification_outbox import process_notification_outbox


async def test_notification_outbox_job_commits_delivery_and_is_idempotent():
    account_id = uuid.uuid4()
    dedupe_key = f"notification-job-{uuid.uuid4().hex}"
    async with AsyncSessionLocal() as session:
        session.add(
            Account(
                id=account_id,
                username=f"outbox_{uuid.uuid4().hex[:8]}",
                password_hash=hash_password("OutboxTestPassword123"),
                role=UserRole.USER,
                full_name="Outbox Test User",
                is_active=True,
            )
        )
        await session.flush()

        notification_repo = NotificationRepository(session)
        telegram_repo = TelegramLinkRepository(session)
        telegram_service = TelegramService(telegram_repo)
        raw_code, link = await telegram_service.generate_link_code(account_id)
        persisted_link = await telegram_repo.get_by_verification_code(raw_code)
        assert persisted_link is not None and persisted_link.id == link.id
        await telegram_repo.complete_link(persisted_link, telegram_user_id=12345, chat_id=67890)

        preference = await notification_repo.get_or_create_preference(account_id)
        await notification_repo.update_preference(preference, {"telegram_enabled": True})
        service = NotificationService(
            notification_repo,
            telegram_repo,
            MockTelegramProvider(),
        )
        await service.emit_notification(
            account_id=account_id,
            type_=NotificationType.DEAL_CREATED,
            title="Deal created",
            message="A deal is available",
            dedupe_key=dedupe_key,
        )
        await session.commit()

    try:
        first = await process_notification_outbox({"job_id": "outbox-test", "job_try": 1})
        second = await process_notification_outbox({"job_id": "outbox-rerun", "job_try": 1})

        assert first["processed"] == 1
        assert second["processed"] == 0

        async with AsyncSessionLocal() as session:
            outbox = (
                await session.execute(
                    select(NotificationOutbox).where(
                        NotificationOutbox.account_id == account_id,
                        NotificationOutbox.dedupe_hash.is_not(None),
                    )
                )
            ).scalar_one()
            assert outbox.status == NotificationStatus.SENT
            assert outbox.attempts == 1
            assert outbox.processed_at is not None
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(Account).where(Account.id == account_id))
            await session.commit()
