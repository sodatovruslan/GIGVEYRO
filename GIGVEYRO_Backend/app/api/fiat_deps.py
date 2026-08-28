from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.account import AccountRepository
from app.repositories.fees import FeeRepository
from app.repositories.fiat_wallet import (
    FiatConversionRepository,
    FiatLedgerRepository,
    FiatWalletRepository,
)
from app.services.fiat_rate.runtime import get_fiat_conversion_rate_service
from app.services.fiat_wallet import FiatWalletService


def get_conversion_rate_dependency():
    return get_fiat_conversion_rate_service()


def get_fiat_wallet_service(
    db: AsyncSession = Depends(get_db), rates=Depends(get_conversion_rate_dependency)
) -> FiatWalletService:
    return FiatWalletService(
        wallets=FiatWalletRepository(db),
        ledger=FiatLedgerRepository(db),
        conversions=FiatConversionRepository(db),
        accounts=AccountRepository(db),
        rates=rates,
        fees=FeeRepository(db),
    )
