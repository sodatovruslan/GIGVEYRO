import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.enums.account import UserRole
from app.models.account import Account
from app.models.auth_session import AuthSession
from app.models.two_factor import TwoFactorChallenge
from app.repositories.account import AccountRepository
from app.repositories.auth_session import AuthSessionRepository
from app.repositories.two_factor import TwoFactorChallengeRepository
from app.workers.arq_settings import WorkerSettings
from app.workers.jobs.session_cleanup import cleanup_expired_sessions


async def test_cleanup_job_is_registered():
    assert cleanup_expired_sessions in WorkerSettings.functions


async def test_cleanup_job_prunes_expired_sessions_and_challenges():
    async with AsyncSessionLocal() as setup_session:
        account = Account(
            username=f"cleanup_job_{uuid.uuid4().hex[:8]}",
            password_hash=hash_password("CleanupJobTest123"),
            role=UserRole.OWNER,
            full_name="Cleanup Job Test",
            is_active=True,
        )
        await AccountRepository(setup_session).create(account)

        expired_session = AuthSession(
            account_id=account.id,
            refresh_token_hash="deadbeef" * 8,
            expires_at=datetime.now(UTC) - timedelta(days=40),
        )
        await AuthSessionRepository(setup_session).create(expired_session)

        expired_challenge = TwoFactorChallenge(
            account_id=account.id,
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        await TwoFactorChallengeRepository(setup_session).create(expired_challenge)

        await setup_session.commit()
        account_id = account.id

    try:
        result = await cleanup_expired_sessions({"job_id": "test", "job_try": 1})
        assert result["status"] == "ok"
        assert result["sessions_deleted"] >= 1
        assert result["two_factor_rows_deleted"] >= 1

        async with AsyncSessionLocal() as verify_session:
            remaining_sessions = (
                await verify_session.execute(
                    select(AuthSession).where(AuthSession.account_id == account_id)
                )
            ).scalars().all()
            assert remaining_sessions == []
            remaining_challenges = (
                await verify_session.execute(
                    select(TwoFactorChallenge).where(TwoFactorChallenge.account_id == account_id)
                )
            ).scalars().all()
            assert remaining_challenges == []
    finally:
        async with AsyncSessionLocal() as cleanup_session:
            await cleanup_session.execute(
                delete(AuthSession).where(AuthSession.account_id == account_id)
            )
            await cleanup_session.execute(
                delete(TwoFactorChallenge).where(TwoFactorChallenge.account_id == account_id)
            )
            await cleanup_session.execute(delete(Account).where(Account.id == account_id))
            await cleanup_session.commit()
