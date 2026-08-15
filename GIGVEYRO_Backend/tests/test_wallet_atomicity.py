from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.enums.account import UserRole
from app.enums.wallet import BalanceBucket, Currency, LedgerEntryType
from app.models.ledger import LedgerEntry


async def test_wallet_and_ledger_changes_roll_back_together(make_account, make_wallet, db_session):
    """If the ledger insert half of a financial mutation fails, the wallet
    balance change made in the same transaction must not survive either -
    this is the invariant WalletService._apply_bucket_change relies on by
    flushing both changes and only committing once, at the end of the
    request. Forces a real NOT NULL violation (no mocking) inside a
    SAVEPOINT so the rest of the test's transaction stays usable.
    """
    user = await make_account(role=UserRole.USER)
    wallet = await make_wallet(user, available=Decimal("100"))

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            wallet.available_balance = Decimal("150")

            bad_entry = LedgerEntry(
                wallet_id=None,  # NOT NULL violation - simulates the ledger insert failing
                account_id=user.id,
                type=LedgerEntryType.OWNER_ALLOCATION,
                balance_bucket=BalanceBucket.AVAILABLE,
                currency=Currency.USDT,
                amount=Decimal("50"),
                available_before=Decimal("100"),
                available_after=Decimal("150"),
                insurance_before=Decimal("0"),
                insurance_after=Decimal("0"),
                frozen_before=Decimal("0"),
                frozen_after=Decimal("0"),
            )
            db_session.add(bad_entry)
            await db_session.flush()

    await db_session.refresh(wallet)
    assert wallet.available_balance == Decimal("100")
