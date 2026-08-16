import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from app.enums.account import UserRole
from app.enums.appeal import AppealReason, AppealResolution, AppealStatus
from app.enums.deal import DealStatus
from app.models.account import Account
from app.models.appeal import DealAppeal
from app.repositories.appeal import AppealRepository
from app.repositories.deal import DealRepository
from app.services.deal import DealNotFoundError, transition_deal
from app.services.wallet import WalletService


class AppealNotFoundError(Exception):
    """Raised when an appeal is missing or not visible to the caller."""


class AppealNotAllowedError(Exception):
    """Raised when creating or modifying an appeal is prohibited."""


class InvalidAppealTransitionError(Exception):
    """Raised when an illegal status change is attempted on an appeal."""


def generate_appeal_public_id() -> str:
    return f"APL-{secrets.token_hex(4).upper()}"


class AppealService:
    def __init__(

        self,
        appeal_repository: AppealRepository,
        deal_repository: DealRepository,
        wallet_service: WalletService,
    ):
        self._appeals = appeal_repository
        self._deals = deal_repository
        self._wallet_service = wallet_service

    async def open_appeal(
        self,
        actor: Account,
        *,
        deal_id: uuid.UUID,
        reason_code: AppealReason,
        message: str,
    ) -> DealAppeal:
        deal = await self._deals.get_by_id_for_update(deal_id)
        if deal is None:
            raise DealNotFoundError()

        if actor.role == UserRole.USER and deal.user_id != actor.id:
            raise AppealNotAllowedError("you are not a participant in this deal")
        elif actor.role == UserRole.MERCHANT and deal.merchant_id != actor.id:
            raise AppealNotAllowedError("you are not a participant in this deal")
        elif actor.role not in (UserRole.USER, UserRole.MERCHANT):
            raise AppealNotAllowedError("only deal participants can open an appeal")

        if deal.status not in (DealStatus.ACCEPTED, DealStatus.PAYMENT_PENDING):
            raise AppealNotAllowedError(
                f"cannot open appeal for deal in status {deal.status}"
            )

        active_appeal = await self._appeals.get_active_by_deal_id(deal.id)
        if active_appeal is not None:
            raise AppealNotAllowedError("an active appeal already exists for this deal")

        previous_deal_status = deal.status

        last_error: IntegrityError | None = None
        for _ in range(3):
            appeal = DealAppeal(
                public_id=generate_appeal_public_id(),
                deal_id=deal.id,
                opened_by_account_id=actor.id,
                opened_by_role=actor.role,
                reason_code=reason_code,
                message=message,
                status=AppealStatus.OPEN,
                previous_deal_status=previous_deal_status,
            )
            try:
                appeal = await self._appeals.create(appeal)
                break
            except IntegrityError as exc:
                last_error = exc
        else:
            raise last_error  # pragma: no cover

        transition_deal(deal, DealStatus.DISPUTED)
        await self._deals.save(deal)

        return appeal

    async def cancel_appeal(
        self, actor: Account, *, appeal_id: uuid.UUID
    ) -> DealAppeal:
        appeal = await self._appeals.get_by_id_for_update(appeal_id)
        if appeal is None:
            raise AppealNotFoundError()

        if appeal.opened_by_account_id != actor.id:
            raise AppealNotAllowedError("only the appeal creator can cancel it")

        if appeal.status != AppealStatus.OPEN:
            raise InvalidAppealTransitionError(
                f"cannot cancel appeal in status {appeal.status}"
            )

        deal = await self._deals.get_by_id_for_update(appeal.deal_id)
        if deal is None:
            raise DealNotFoundError()

        appeal.status = AppealStatus.CANCELLED
        saved_appeal = await self._appeals.save(appeal)

        transition_deal(deal, appeal.previous_deal_status)
        await self._deals.save(deal)

        return saved_appeal

    async def get_for_participant(
        self, actor: Account, appeal_id: uuid.UUID
    ) -> DealAppeal:
        appeal = await self._appeals.get_by_id(appeal_id)
        if appeal is None:
            raise AppealNotFoundError()

        deal = await self._deals.get_by_id(appeal.deal_id)
        if deal is None:
            raise AppealNotFoundError()

        if actor.role == UserRole.USER and deal.user_id != actor.id:
            raise AppealNotFoundError()
        if actor.role == UserRole.MERCHANT and deal.merchant_id != actor.id:
            raise AppealNotFoundError()

        return appeal

    async def list_for_participant(
        self,
        actor: Account,
        *,
        status: AppealStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[DealAppeal], int]:
        items = await self._appeals.list_for_account(
            actor.id, status=status, limit=limit, offset=offset
        )
        total = await self._appeals.count_for_account(actor.id, status=status)
        return items, total

    # -- OWNER ACTIONS ----------------------------------------------------

    async def take_under_review(
        self, owner_id: uuid.UUID, appeal_id: uuid.UUID, owner_note: str | None = None
    ) -> DealAppeal:
        appeal = await self._appeals.get_by_id_for_update(appeal_id)
        if appeal is None:
            raise AppealNotFoundError()

        if appeal.status == AppealStatus.UNDER_REVIEW:
            return appeal

        if appeal.status != AppealStatus.OPEN:
            raise InvalidAppealTransitionError(
                f"cannot take under review appeal in status {appeal.status}"
            )

        appeal.status = AppealStatus.UNDER_REVIEW
        if owner_note:
            appeal.owner_note = owner_note

        return await self._appeals.save(appeal)

    async def resolve_appeal(
        self,
        owner_id: uuid.UUID,
        appeal_id: uuid.UUID,
        *,
        resolution: AppealResolution,
        owner_note: str,
    ) -> DealAppeal:
        appeal = await self._appeals.get_by_id_for_update(appeal_id)
        if appeal is None:
            raise AppealNotFoundError()

        if appeal.status == AppealStatus.RESOLVED:
            return appeal

        if appeal.status not in (AppealStatus.OPEN, AppealStatus.UNDER_REVIEW):
            raise InvalidAppealTransitionError(
                f"cannot resolve appeal in status {appeal.status}"
            )

        deal = await self._deals.get_by_id_for_update(appeal.deal_id)
        if deal is None:
            raise DealNotFoundError()

        if deal.user_id is None or deal.amount_usdt is None:
            raise AppealNotAllowedError("deal missing participant user or amount_usdt")

        if resolution == AppealResolution.RELEASE_TO_USER:
            await self._wallet_service.release_for_deal(
                user_account_id=deal.user_id,
                amount=deal.amount_usdt,
                deal_id=deal.id,
            )
            transition_deal(deal, DealStatus.CANCELLED)

        elif resolution == AppealResolution.SETTLE_TO_MERCHANT:
            await self._wallet_service.settle_deal(
                user_account_id=deal.user_id,
                merchant_account_id=deal.merchant_id,
                amount=deal.amount_usdt,
                deal_id=deal.id,
                actor_id=owner_id,
            )
            transition_deal(deal, DealStatus.COMPLETED)

        await self._deals.save(deal)

        appeal.status = AppealStatus.RESOLVED
        appeal.resolution = resolution
        appeal.owner_note = owner_note
        appeal.resolved_by_account_id = owner_id
        appeal.resolved_at = datetime.now(UTC)

        return await self._appeals.save(appeal)

    async def get_for_owner(self, appeal_id: uuid.UUID) -> DealAppeal:
        appeal = await self._appeals.get_by_id(appeal_id)
        if appeal is None:
            raise AppealNotFoundError()
        return appeal

    async def list_for_owner(
        self,
        *,
        status: AppealStatus | None,
        reason_code: AppealReason | None,
        merchant_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[DealAppeal], int]:
        items = await self._appeals.list_all(
            status=status,
            reason_code=reason_code,
            merchant_id=merchant_id,
            user_id=user_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        total = await self._appeals.count_all(
            status=status,
            reason_code=reason_code,
            merchant_id=merchant_id,
            user_id=user_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        return items, total
