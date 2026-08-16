import secrets
import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.enums.account import UserRole
from app.enums.appeal import AppealReason
from app.enums.deal import DealStatus
from app.models.account import Account
from app.models.appeal import DealAppeal
from app.models.deal import Deal
from app.repositories.account import AccountRepository
from app.repositories.deal import DealRepository
from app.repositories.payment_requisite import PaymentRequisiteRepository
from app.repositories.traffic import TrafficRepository
from app.schemas.payment_requisite import mask_card_number
from app.services.exchange_rate import ExchangeRateProvider
from app.services.wallet import WalletService

USDT_QUANTUM = Decimal("0.00000001")

_TERMINAL_TIMESTAMP_FIELD = {
    DealStatus.ACCEPTED: "accepted_at",
    DealStatus.COMPLETED: "completed_at",
    DealStatus.CANCELLED: "cancelled_at",
}

ALLOWED_TRANSITIONS: dict[DealStatus, set[DealStatus]] = {
    DealStatus.CREATED: {DealStatus.AVAILABLE},
    DealStatus.AVAILABLE: {DealStatus.ACCEPTED, DealStatus.CANCELLED, DealStatus.EXPIRED},
    DealStatus.ACCEPTED: {
        DealStatus.PAYMENT_PENDING,
        DealStatus.COMPLETED,
        DealStatus.CANCELLED,
        DealStatus.DISPUTED,
    },
    DealStatus.PAYMENT_PENDING: {
        DealStatus.COMPLETED,
        DealStatus.CANCELLED,
        DealStatus.DISPUTED,
    },
    DealStatus.DISPUTED: {
        DealStatus.COMPLETED,
        DealStatus.CANCELLED,
        DealStatus.ACCEPTED,
        DealStatus.PAYMENT_PENDING,
    },
    DealStatus.COMPLETED: set(),
    DealStatus.CANCELLED: set(),
    DealStatus.EXPIRED: set(),
}


class DealNotFoundError(Exception):
    """Covers a missing deal and one that exists but isn't visible."""


class DealCreationNotAllowedError(Exception):
    """Raised when a non-MERCHANT account attempts to create a deal."""


class InvalidDealTransitionError(Exception):
    """Raised when a deal status change isn't in ALLOWED_TRANSITIONS."""


class DealNotAvailableError(Exception):
    """Raised when accept targets a deal that isn't AVAILABLE."""


class UserNotEligibleError(Exception):
    """Raised when the accepting USER's account/traffic state blocks accepting deals."""


class RequisiteNotEligibleError(Exception):
    """Raised when the chosen requisite isn't usable."""


def generate_public_id() -> str:
    return f"D-{secrets.token_hex(4).upper()}"


def calculate_amount_usdt(amount_tjs: Decimal, rate: Decimal) -> Decimal:
    return (amount_tjs / rate).quantize(USDT_QUANTUM, rounding=ROUND_HALF_UP)


def transition_deal(deal: Deal, new_status: DealStatus) -> None:
    if new_status not in ALLOWED_TRANSITIONS.get(deal.status, set()):
        raise InvalidDealTransitionError(
            f"cannot transition deal from {deal.status} to {new_status}"
        )
    deal.status = new_status
    timestamp_field = _TERMINAL_TIMESTAMP_FIELD.get(new_status)
    if timestamp_field is not None:
        setattr(deal, timestamp_field, datetime.now(UTC))


class DealService:
    def __init__(
        self,
        deal_repository: DealRepository,
        requisite_repository: PaymentRequisiteRepository,
        traffic_repository: TrafficRepository,
        account_repository: AccountRepository,
        wallet_service: WalletService,
        rate_provider: ExchangeRateProvider,
        appeal_service=None,
    ):
        self._deals = deal_repository
        self._requisites = requisite_repository
        self._traffic = traffic_repository
        self._accounts = account_repository
        self._wallet_service = wallet_service
        self._rate_provider = rate_provider
        self._appeal_service = appeal_service

    # -- MERCHANT -------------------------------------------------------

    async def create_deal(self, merchant: Account, *, amount_tjs: Decimal) -> Deal:
        if merchant.role != UserRole.MERCHANT:
            raise DealCreationNotAllowedError("only MERCHANT accounts can create deals")

        expires_at = datetime.now(UTC) + timedelta(minutes=settings.DEAL_TTL_MINUTES)

        last_error: IntegrityError | None = None
        for _ in range(3):
            deal = Deal(
                public_id=generate_public_id(),
                merchant_id=merchant.id,
                amount_tjs=amount_tjs,
                status=DealStatus.CREATED,
                expires_at=expires_at,
            )
            try:
                deal = await self._deals.create(deal)
                break
            except IntegrityError as exc:
                last_error = exc
        else:
            raise last_error

        transition_deal(deal, DealStatus.AVAILABLE)
        return await self._deals.save(deal)

    async def get_for_merchant(self, merchant_id: uuid.UUID, deal_id: uuid.UUID) -> Deal:
        deal = await self._get_or_raise(deal_id)
        if deal.merchant_id != merchant_id:
            raise DealNotFoundError()
        return await self._expire_if_needed(deal)

    async def list_for_merchant(
        self, merchant_id: uuid.UUID, *, status: DealStatus | None, limit: int, offset: int
    ) -> tuple[list[Deal], int]:
        await self._deals.expire_stale_available()
        items = await self._deals.list_for_merchant(
            merchant_id, status=status, limit=limit, offset=offset
        )
        total = await self._deals.count_for_merchant(merchant_id, status=status)
        return items, total

    async def mark_paid_by_merchant(
        self,
        merchant_id: uuid.UUID,
        deal_id: uuid.UUID,
        *,
        payment_reference: str | None = None,
        payment_note: str | None = None,
    ) -> Deal:
        deal = await self._deals.get_by_id_for_update(deal_id)
        if deal is None or deal.merchant_id != merchant_id:
            raise DealNotFoundError()

        if deal.status == DealStatus.PAYMENT_PENDING:
            return deal

        if deal.status != DealStatus.ACCEPTED:
            raise InvalidDealTransitionError(
                f"cannot mark paid for deal in status {deal.status}"
            )

        deal.merchant_marked_paid_at = datetime.now(UTC)
        if payment_reference:
            deal.payment_reference = payment_reference.strip()
        if payment_note:
            deal.payment_note = payment_note.strip()

        transition_deal(deal, DealStatus.PAYMENT_PENDING)
        return await self._deals.save(deal)

    # -- USER -------------------------------------------------------------

    async def list_available_for_user(
        self, account_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[Deal], int]:
        await self._ensure_user_eligible(account_id)
        await self._deals.expire_stale_available()
        items = await self._deals.list_available(limit=limit, offset=offset)
        total = await self._deals.count_available()
        return items, total

    async def get_own_for_user(self, user_id: uuid.UUID, deal_id: uuid.UUID) -> Deal:
        deal = await self._get_or_raise(deal_id)
        if deal.user_id != user_id:
            raise DealNotFoundError()
        return await self._expire_if_needed(deal)

    async def list_own_for_user(
        self, user_id: uuid.UUID, *, status: DealStatus | None, limit: int, offset: int
    ) -> tuple[list[Deal], int]:
        items = await self._deals.list_for_user(user_id, status=status, limit=limit, offset=offset)
        total = await self._deals.count_for_user(user_id, status=status)
        return items, total

    async def accept_deal(
        self, *, account: Account, deal_id: uuid.UUID, requisite_id: uuid.UUID
    ) -> Deal:
        deal = await self._deals.get_by_id_for_update(deal_id)
        if deal is None:
            raise DealNotFoundError()

        await self._expire_if_needed(deal)

        if deal.status != DealStatus.AVAILABLE or deal.user_id is not None:
            raise DealNotAvailableError("deal is no longer available")

        await self._ensure_user_eligible(account.id, account=account)

        requisite = await self._requisites.get_by_id(requisite_id)
        if requisite is None or requisite.account_id != account.id:
            raise RequisiteNotEligibleError("requisite not found")
        if requisite.is_archived or not requisite.is_active:
            raise RequisiteNotEligibleError("requisite is not active")

        rate = await self._rate_provider.get_usdt_tjs_rate()
        amount_usdt = calculate_amount_usdt(deal.amount_tjs, rate)

        await self._wallet_service.freeze_for_deal(
            account_id=account.id, amount=amount_usdt, deal_id=deal.id
        )

        deal.user_id = account.id
        deal.payment_requisite_id = requisite.id
        deal.requisite_type = requisite.type
        deal.requisite_bank_name = requisite.bank_name
        deal.requisite_holder_name = requisite.holder_name
        deal.requisite_masked_card_number = mask_card_number(requisite.card_number)
        deal.exchange_rate = rate
        deal.amount_usdt = amount_usdt
        transition_deal(deal, DealStatus.ACCEPTED)

        return await self._deals.save(deal)

    async def confirm_received_by_user(self, user: Account, deal_id: uuid.UUID) -> Deal:
        deal = await self._deals.get_by_id_for_update(deal_id)
        if deal is None or deal.user_id != user.id:
            raise DealNotFoundError()

        if deal.status == DealStatus.COMPLETED:
            return deal

        if deal.status != DealStatus.PAYMENT_PENDING:
            raise InvalidDealTransitionError(
                f"cannot confirm received for deal in status {deal.status}"
            )

        if deal.amount_usdt is None:
            raise InvalidDealTransitionError("deal is missing amount_usdt")

        await self._wallet_service.settle_deal(
            user_account_id=user.id,
            merchant_account_id=deal.merchant_id,
            amount=deal.amount_usdt,
            deal_id=deal.id,
            actor_id=user.id,
        )

        deal.user_confirmed_received_at = datetime.now(UTC)
        transition_deal(deal, DealStatus.COMPLETED)
        return await self._deals.save(deal)

    async def report_payment_problem_by_user(
        self,
        user: Account,
        deal_id: uuid.UUID,
        *,
        reason_code: AppealReason,
        message: str,
    ) -> tuple[Deal, DealAppeal | None]:
        deal = await self._deals.get_by_id_for_update(deal_id)
        if deal is None or deal.user_id != user.id:
            raise DealNotFoundError()

        if deal.status == DealStatus.DISPUTED:
            appeal = None
            if self._appeal_service is not None:
                appeal = await self._appeal_service.get_for_participant(user, deal.id)
            return deal, appeal

        if deal.status != DealStatus.PAYMENT_PENDING:
            raise InvalidDealTransitionError(
                f"cannot report payment problem for deal in status {deal.status}"
            )

        deal.user_rejected_payment_at = datetime.now(UTC)

        appeal = None
        if self._appeal_service is not None:
            appeal = await self._appeal_service.open_appeal(
                user,
                deal_id=deal.id,
                reason_code=reason_code,
                message=message,
            )
        else:
            transition_deal(deal, DealStatus.DISPUTED)
            await self._deals.save(deal)

        return deal, appeal

    # -- STAGE 9: SETTLEMENT & RELEASE ----------------------------------

    async def complete_deal(self, deal_id: uuid.UUID, *, actor_id: uuid.UUID | None = None) -> Deal:
        """Completes a deal (Settlement): User frozen -= USDT, Merchant available += USDT."""
        deal = await self._deals.get_by_id_for_update(deal_id)
        if deal is None:
            raise DealNotFoundError()

        if deal.status == DealStatus.COMPLETED:
            return deal

        if deal.status == DealStatus.DISPUTED:
            raise InvalidDealTransitionError("cannot complete a disputed deal directly")

        if deal.status not in (DealStatus.ACCEPTED, DealStatus.PAYMENT_PENDING):
            raise InvalidDealTransitionError(f"cannot complete deal in status {deal.status}")

        if deal.user_id is None or deal.amount_usdt is None:
            raise InvalidDealTransitionError("deal is missing accepted user or amount_usdt")

        await self._wallet_service.settle_deal(
            user_account_id=deal.user_id,
            merchant_account_id=deal.merchant_id,
            amount=deal.amount_usdt,
            deal_id=deal.id,
            actor_id=actor_id,
        )

        transition_deal(deal, DealStatus.COMPLETED)
        return await self._deals.save(deal)

    async def cancel_or_release_deal(
        self, deal_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> Deal:
        """Cancels/releases an accepted deal: User frozen -= USDT, User available += USDT."""
        deal = await self._deals.get_by_id_for_update(deal_id)
        if deal is None:
            raise DealNotFoundError()

        if deal.status == DealStatus.CANCELLED:
            return deal

        if deal.status == DealStatus.DISPUTED:
            raise InvalidDealTransitionError("cannot release a disputed deal directly")

        if deal.status not in (DealStatus.ACCEPTED, DealStatus.PAYMENT_PENDING):
            raise InvalidDealTransitionError(f"cannot release deal in status {deal.status}")

        if deal.user_id is None or deal.amount_usdt is None:
            raise InvalidDealTransitionError("deal is missing accepted user or amount_usdt")

        await self._wallet_service.release_for_deal(
            user_account_id=deal.user_id, amount=deal.amount_usdt, deal_id=deal.id
        )

        transition_deal(deal, DealStatus.CANCELLED)
        return await self._deals.save(deal)

    # -- OWNER (read-only) ------------------------------------------------

    async def get_for_owner(self, deal_id: uuid.UUID) -> Deal:
        deal = await self._get_or_raise(deal_id)
        return await self._expire_if_needed(deal)

    async def list_for_owner(
        self,
        *,
        status: DealStatus | None,
        merchant_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Deal], int]:
        await self._deals.expire_stale_available()
        items = await self._deals.list_all(
            status=status,
            merchant_id=merchant_id,
            user_id=user_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        total = await self._deals.count_all(
            status=status,
            merchant_id=merchant_id,
            user_id=user_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        return items, total

    # -- internal -----------------------------------------------------------

    async def _get_or_raise(self, deal_id: uuid.UUID) -> Deal:
        deal = await self._deals.get_by_id(deal_id)
        if deal is None:
            raise DealNotFoundError()
        return deal

    async def _expire_if_needed(self, deal: Deal) -> Deal:
        if deal.status == DealStatus.AVAILABLE and deal.expires_at <= datetime.now(UTC):
            transition_deal(deal, DealStatus.EXPIRED)
            await self._deals.save(deal)
        return deal

    async def _ensure_user_eligible(
        self, account_id: uuid.UUID, *, account: Account | None = None
    ) -> None:
        if account is None:
            account = await self._accounts.get_by_id(account_id)
        if account is None or account.role != UserRole.USER:
            raise UserNotEligibleError("account is not eligible to accept deals")
        if not account.is_active:
            raise UserNotEligibleError("account is inactive")

        traffic = await self._traffic.get_by_account_id(account_id)
        if traffic is None or not traffic.is_enabled:
            raise UserNotEligibleError("traffic is disabled")
