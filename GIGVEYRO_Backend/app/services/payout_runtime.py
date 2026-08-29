from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.account import AccountRepository
from app.repositories.audit import AuditRepository
from app.repositories.ledger import LedgerRepository
from app.repositories.merchant_wallet import MerchantWalletRepository
from app.repositories.notification import NotificationRepository
from app.repositories.payout import PayoutRepository
from app.repositories.realtime import RealtimeOutboxRepository
from app.repositories.risk import RiskRepository
from app.repositories.telegram import TelegramLinkRepository
from app.repositories.wallet import WalletRepository
from app.repositories.withdrawal import WithdrawalRepository
from app.services.audit import AuditService
from app.services.notification import NotificationService
from app.services.payout import ControlledPayoutService
from app.services.realtime import RealtimeEventService
from app.services.telegram_provider import MockTelegramProvider
from app.services.wallet import WalletService


def build_controlled_payout_service(db: AsyncSession) -> ControlledPayoutService:
    accounts = AccountRepository(db)
    wallet = WalletService(
        WalletRepository(db), LedgerRepository(db), accounts, MerchantWalletRepository(db)
    )
    return ControlledPayoutService(
        PayoutRepository(db),
        WithdrawalRepository(db),
        RiskRepository(db),
        wallet,
        accounts,
        audit=AuditService(AuditRepository(db)),
        notifications=NotificationService(
            NotificationRepository(db), TelegramLinkRepository(db), MockTelegramProvider()
        ),
        realtime=RealtimeEventService(RealtimeOutboxRepository(db)),
    )
