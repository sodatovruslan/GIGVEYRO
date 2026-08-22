import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.two_factor import (
    AccountTwoFactor,
    PendingTwoFactorSetup,
    TwoFactorChallenge,
    TwoFactorRecoveryCode,
)


class AccountTwoFactorRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_account_id(self, account_id: uuid.UUID) -> AccountTwoFactor | None:
        result = await self._session.execute(
            select(AccountTwoFactor).where(AccountTwoFactor.account_id == account_id)
        )
        return result.scalar_one_or_none()

    async def create(self, record: AccountTwoFactor) -> AccountTwoFactor:
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        return record

    async def delete_for_account(self, account_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(AccountTwoFactor).where(AccountTwoFactor.account_id == account_id)
        )


class PendingTwoFactorSetupRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_account_id(self, account_id: uuid.UUID) -> PendingTwoFactorSetup | None:
        result = await self._session.execute(
            select(PendingTwoFactorSetup).where(PendingTwoFactorSetup.account_id == account_id)
        )
        return result.scalar_one_or_none()

    async def replace_for_account(self, record: PendingTwoFactorSetup) -> PendingTwoFactorSetup:
        await self._session.execute(
            delete(PendingTwoFactorSetup).where(
                PendingTwoFactorSetup.account_id == record.account_id
            )
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        return record

    async def delete_for_account(self, account_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(PendingTwoFactorSetup).where(PendingTwoFactorSetup.account_id == account_id)
        )

    async def prune_expired(self, older_than: datetime) -> int:
        result = await self._session.execute(
            delete(PendingTwoFactorSetup).where(PendingTwoFactorSetup.expires_at < older_than)
        )
        return result.rowcount or 0


class TwoFactorRecoveryCodeRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def replace_for_account(
        self, account_id: uuid.UUID, records: list[TwoFactorRecoveryCode]
    ) -> None:
        await self._session.execute(
            delete(TwoFactorRecoveryCode).where(TwoFactorRecoveryCode.account_id == account_id)
        )
        for record in records:
            self._session.add(record)
        await self._session.flush()

    async def get_unused_by_hash(
        self, account_id: uuid.UUID, code_hash: str
    ) -> TwoFactorRecoveryCode | None:
        result = await self._session.execute(
            select(TwoFactorRecoveryCode).where(
                TwoFactorRecoveryCode.account_id == account_id,
                TwoFactorRecoveryCode.code_hash == code_hash,
                TwoFactorRecoveryCode.used_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def mark_used(self, record: TwoFactorRecoveryCode) -> None:
        record.used_at = datetime.now(UTC)
        await self._session.flush()

    async def count_unused(self, account_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(TwoFactorRecoveryCode).where(
                TwoFactorRecoveryCode.account_id == account_id,
                TwoFactorRecoveryCode.used_at.is_(None),
            )
        )
        return len(result.scalars().all())

    async def delete_for_account(self, account_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(TwoFactorRecoveryCode).where(TwoFactorRecoveryCode.account_id == account_id)
        )


class TwoFactorChallengeRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, record: TwoFactorChallenge) -> TwoFactorChallenge:
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        return record

    async def get_by_id_for_update(self, challenge_id: uuid.UUID) -> TwoFactorChallenge | None:
        result = await self._session.execute(
            select(TwoFactorChallenge)
            .where(TwoFactorChallenge.id == challenge_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def update(self, record: TwoFactorChallenge) -> TwoFactorChallenge:
        await self._session.flush()
        await self._session.refresh(record)
        return record

    async def prune_expired(self, older_than: datetime) -> int:
        result = await self._session.execute(
            delete(TwoFactorChallenge).where(TwoFactorChallenge.expires_at < older_than)
        )
        return result.rowcount or 0
