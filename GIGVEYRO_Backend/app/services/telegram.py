import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.infra.metrics import record_telegram_connection
from app.models.account import Account
from app.models.telegram import TelegramAccountLink
from app.repositories.audit import AuditRepository
from app.repositories.telegram import TelegramLinkRepository
from app.services.audit import AuditService
from app.telegram_bot.i18n import normalize_language

logger = logging.getLogger(__name__)


class TelegramLinkError(Exception):
    """Safe, deliberately non-enumerating link failure."""


@dataclass(frozen=True)
class TelegramLinkResult:
    connection: TelegramAccountLink
    language: str


class TelegramService:
    def __init__(self, telegram_repo: TelegramLinkRepository):
        self.telegram_repo = telegram_repo
        self._session = telegram_repo.session
        self._audit = AuditService(AuditRepository(self._session))

    async def generate_link_token(self, account: Account) -> tuple[str, datetime]:
        now = datetime.now(UTC)
        raw_token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(minutes=settings.TELEGRAM_LINK_TOKEN_TTL_MINUTES)
        await self.telegram_repo.revoke_unused_tokens(account.id, now)
        await self.telegram_repo.create_token(account.id, raw_token, expires_at)
        await self._audit.log_action(
            action="telegram.link_token_created",
            entity_type="telegram_connection",
            actor_account_id=account.id,
            actor_role=account.role.value,
            entity_id=str(account.id),
            audit_metadata={"expires_at": expires_at.isoformat()},
        )
        return raw_token, expires_at

    async def consume_link_token(
        self,
        *,
        raw_token: str,
        telegram_user_id: int,
        chat_id: int,
        username: str | None,
        first_name: str | None,
        telegram_language: str | None,
    ) -> TelegramLinkResult:
        now = datetime.now(UTC)
        token = await self.telegram_repo.get_token_for_update(raw_token)
        if (
            token is None
            or token.used_at is not None
            or token.revoked_at is not None
            or token.expires_at <= now
        ):
            raise TelegramLinkError

        account = (
            await self._session.execute(
                select(Account).where(Account.id == token.account_id).with_for_update()
            )
        ).scalar_one_or_none()
        if account is None or not account.is_active:
            raise TelegramLinkError

        conflict = await self.telegram_repo.get_by_telegram_user_id(
            telegram_user_id, for_update=True
        )
        if conflict is not None and conflict.account_id != account.id:
            raise TelegramLinkError

        language = normalize_language(telegram_language)
        existing_account_connection = await self.telegram_repo.get_by_account_id(account.id)
        was_linked = bool(existing_account_connection and existing_account_connection.is_linked)
        try:
            async with self._session.begin_nested():
                connection = await self.telegram_repo.activate_connection(
                    account_id=account.id,
                    telegram_user_id=telegram_user_id,
                    chat_id=chat_id,
                    username=username,
                    first_name=first_name,
                    language=language,
                    now=now,
                )
                token.used_at = now
                await self._audit.log_action(
                    action="telegram.connected",
                    entity_type="telegram_connection",
                    actor_account_id=account.id,
                    actor_role=account.role.value,
                    entity_id=str(connection.id),
                    audit_metadata={"language": language},
                )
                await self._session.flush()
        except IntegrityError as exc:
            raise TelegramLinkError from exc
        if not was_linked:
            record_telegram_connection(1)
        logger.info("telegram.connection.linked")
        return TelegramLinkResult(connection=connection, language=language)

    async def disconnect(self, connection: TelegramAccountLink, account: Account) -> None:
        was_linked = connection.is_linked
        await self.telegram_repo.disconnect(connection, datetime.now(UTC))
        await self._audit.log_action(
            action="telegram.disconnected",
            entity_type="telegram_connection",
            actor_account_id=account.id,
            actor_role=account.role.value,
            entity_id=str(connection.id),
        )
        if was_linked:
            record_telegram_connection(-1)
        logger.info("telegram.connection.unlinked")

    async def change_language(
        self, connection: TelegramAccountLink, account: Account, language: str
    ) -> None:
        normalized = normalize_language(language)
        if normalized != language.lower():
            raise ValueError("unsupported language")
        await self.telegram_repo.update_language(connection, normalized, datetime.now(UTC))
        await self._audit.log_action(
            action="telegram.language_changed",
            entity_type="telegram_connection",
            actor_account_id=account.id,
            actor_role=account.role.value,
            entity_id=str(connection.id),
            audit_metadata={"language": normalized},
        )

    async def change_delivery(
        self, connection: TelegramAccountLink, account: Account, enabled: bool
    ) -> None:
        await self.telegram_repo.update_delivery(connection, enabled, datetime.now(UTC))
        await self._audit.log_action(
            action="telegram.delivery_enabled" if enabled else "telegram.delivery_disabled",
            entity_type="telegram_connection",
            actor_account_id=account.id,
            actor_role=account.role.value,
            entity_id=str(connection.id),
            audit_metadata={"reason": "user_preference"},
        )
