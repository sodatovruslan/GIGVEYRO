import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pyotp

from app.core.config import settings
from app.core.security import hash_recovery_code, verify_password
from app.core.totp_crypto import decrypt_totp_secret, encrypt_totp_secret
from app.models.account import Account
from app.models.two_factor import (
    AccountTwoFactor,
    PendingTwoFactorSetup,
    TwoFactorChallenge,
    TwoFactorRecoveryCode,
)
from app.repositories.two_factor import (
    AccountTwoFactorRepository,
    PendingTwoFactorSetupRepository,
    TwoFactorChallengeRepository,
    TwoFactorRecoveryCodeRepository,
)

_ISSUER = "GIGVEYRO"
# No ambiguous characters (0/O, 1/I/L) so codes are easy to transcribe by hand.
_RECOVERY_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class TwoFactorError(Exception):
    """Base class for all 2FA errors."""


class TwoFactorAlreadyEnabledError(TwoFactorError):
    pass


class TwoFactorNotEnabledError(TwoFactorError):
    pass


class InvalidPasswordError(TwoFactorError):
    pass


class SetupExpiredError(TwoFactorError):
    pass


class InvalidCodeError(TwoFactorError):
    pass


class ChallengeInvalidError(TwoFactorError):
    """Challenge missing, expired, already consumed, or account mismatch."""


class ChallengeLockedError(TwoFactorError):
    """Too many failed attempts against this specific challenge."""


def _looks_like_totp(code: str) -> bool:
    return code.isdigit() and len(code) == 6


def _generate_recovery_code() -> str:
    body = "".join(secrets.choice(_RECOVERY_CODE_ALPHABET) for _ in range(8))
    return f"{body[:4]}-{body[4:]}"


class TwoFactorService:
    def __init__(
        self,
        two_factor_repo: AccountTwoFactorRepository,
        pending_repo: PendingTwoFactorSetupRepository,
        recovery_repo: TwoFactorRecoveryCodeRepository,
        challenge_repo: TwoFactorChallengeRepository,
    ):
        self._two_factor = two_factor_repo
        self._pending = pending_repo
        self._recovery = recovery_repo
        self._challenges = challenge_repo

    async def get_status(self, account_id: uuid.UUID) -> AccountTwoFactor | None:
        return await self._two_factor.get_by_account_id(account_id)

    async def count_unused_recovery_codes(self, account_id: uuid.UUID) -> int:
        return await self._recovery.count_unused(account_id)

    async def start_setup(
        self, account: Account, password: str | None, *, password_verified: bool = False
    ) -> PendingTwoFactorSetup:
        if not password_verified:
            if password is None or not verify_password(password, account.password_hash):
                raise InvalidPasswordError()
        if await self._two_factor.get_by_account_id(account.id) is not None:
            raise TwoFactorAlreadyEnabledError()

        secret = pyotp.random_base32()
        pending = PendingTwoFactorSetup(
            account_id=account.id,
            encrypted_secret=encrypt_totp_secret(secret),
            expires_at=datetime.now(UTC)
            + timedelta(minutes=settings.TWO_FACTOR_SETUP_EXPIRE_MINUTES),
        )
        return await self._pending.replace_for_account(pending)

    @staticmethod
    def build_otpauth_uri(account: Account, secret: str) -> str:
        return pyotp.TOTP(secret).provisioning_uri(name=account.username, issuer_name=_ISSUER)

    @staticmethod
    def format_manual_key(secret: str) -> str:
        return " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))

    async def confirm_setup(
        self, account: Account, totp_code: str
    ) -> tuple[AccountTwoFactor, list[str]]:
        pending = await self._pending.get_by_account_id(account.id)
        if pending is None or pending.expires_at <= datetime.now(UTC):
            raise SetupExpiredError()

        secret = decrypt_totp_secret(pending.encrypted_secret)
        if not pyotp.TOTP(secret).verify(totp_code, valid_window=1):
            raise InvalidCodeError()

        record = await self._two_factor.create(
            AccountTwoFactor(
                account_id=account.id,
                method="totp",
                encrypted_secret=pending.encrypted_secret,
                enabled_at=datetime.now(UTC),
            )
        )
        await self._pending.delete_for_account(account.id)
        codes = await self._issue_recovery_codes(account.id)
        return record, codes

    async def regenerate_recovery_codes(
        self, account: Account, password: str, code: str
    ) -> list[str]:
        await self.require_password_and_code(account, password, code)
        return await self._issue_recovery_codes(account.id)

    async def _issue_recovery_codes(self, account_id: uuid.UUID) -> list[str]:
        plaintext_codes = [
            _generate_recovery_code() for _ in range(settings.TWO_FACTOR_RECOVERY_CODE_COUNT)
        ]
        records = [
            TwoFactorRecoveryCode(account_id=account_id, code_hash=hash_recovery_code(code))
            for code in plaintext_codes
        ]
        await self._recovery.replace_for_account(account_id, records)
        return plaintext_codes

    async def require_password_and_code(
        self, account: Account, password: str, code: str
    ) -> AccountTwoFactor:
        if not verify_password(password, account.password_hash):
            raise InvalidPasswordError()

        two_factor = await self._two_factor.get_by_account_id(account.id)
        if two_factor is None:
            raise TwoFactorNotEnabledError()

        if _looks_like_totp(code):
            secret = decrypt_totp_secret(two_factor.encrypted_secret)
            if not pyotp.TOTP(secret).verify(code, valid_window=1):
                raise InvalidCodeError()
        elif not await self._consume_recovery_code(account.id, code):
            raise InvalidCodeError()

        return two_factor

    async def disable(self, account: Account, password: str, code: str) -> None:
        await self.require_password_and_code(account, password, code)

        await self._two_factor.delete_for_account(account.id)
        await self._recovery.delete_for_account(account.id)
        await self._pending.delete_for_account(account.id)

    async def _consume_recovery_code(self, account_id: uuid.UUID, code: str) -> bool:
        record = await self._recovery.get_unused_by_hash(account_id, hash_recovery_code(code))
        if record is None:
            return False
        await self._recovery.mark_used(record)
        return True

    async def create_challenge(self, account: Account) -> TwoFactorChallenge:
        challenge = TwoFactorChallenge(
            account_id=account.id,
            expires_at=datetime.now(UTC)
            + timedelta(seconds=settings.TWO_FACTOR_CHALLENGE_EXPIRE_SECONDS),
        )
        return await self._challenges.create(challenge)

    async def verify_challenge(self, challenge_id: uuid.UUID, account: Account, code: str) -> bool:
        """Returns True if a recovery code was used (vs a TOTP code)."""
        challenge = await self._challenges.get_by_id_for_update(challenge_id)
        now = datetime.now(UTC)

        if challenge is None or challenge.account_id != account.id:
            raise ChallengeInvalidError()
        if challenge.consumed_at is not None or challenge.expires_at <= now:
            raise ChallengeInvalidError()
        if challenge.attempts >= settings.TWO_FACTOR_MAX_CHALLENGE_ATTEMPTS:
            challenge.consumed_at = now
            await self._challenges.update(challenge)
            raise ChallengeLockedError()

        two_factor = await self._two_factor.get_by_account_id(account.id)
        if two_factor is None:
            # Shouldn't happen (a challenge is only ever created for an
            # account with 2FA enabled) - fail safe rather than 500.
            challenge.consumed_at = now
            await self._challenges.update(challenge)
            raise ChallengeInvalidError()

        is_recovery = not _looks_like_totp(code)
        if is_recovery:
            valid = await self._consume_recovery_code(account.id, code)
        else:
            secret = decrypt_totp_secret(two_factor.encrypted_secret)
            valid = pyotp.TOTP(secret).verify(code, valid_window=1)

        if not valid:
            challenge.attempts += 1
            await self._challenges.update(challenge)
            raise InvalidCodeError()

        challenge.consumed_at = now
        await self._challenges.update(challenge)
        return is_recovery

    async def cleanup_expired(self) -> int:
        """Delete expired challenges and abandoned pending setups.

        Not scheduled by this service - a production worker/cron should
        call this periodically, same as AuthService.cleanup_expired_sessions.
        """
        now = datetime.now(UTC)
        challenge_count = await self._challenges.prune_expired(now)
        pending_count = await self._pending.prune_expired(now)
        return challenge_count + pending_count
