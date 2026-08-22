import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

_password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _password_hasher.verify(plain_password, password_hash)


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"
    REALTIME = "realtime"
    TWO_FACTOR_CHALLENGE = "two_factor_challenge"


class TokenError(Exception):
    """Raised when a JWT is missing, malformed, expired, or of the wrong type."""


def _create_token(
    subject: uuid.UUID,
    role: str,
    token_type: TokenType,
    expires_delta: timedelta,
    session_id: uuid.UUID | None = None,
    jti: uuid.UUID | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(jti) if jti is not None else str(uuid.uuid4()),
    }
    if session_id is not None:
        payload["session_id"] = str(session_id)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: uuid.UUID, role: str, session_id: uuid.UUID | None = None) -> str:
    return _create_token(
        subject,
        role,
        TokenType.ACCESS,
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        session_id=session_id,
    )


def create_refresh_token(subject: uuid.UUID, role: str, session_id: uuid.UUID | None = None) -> str:
    return _create_token(
        subject,
        role,
        TokenType.REFRESH,
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        session_id=session_id,
    )


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_refresh_token(token: str) -> str:
    # Refresh tokens are never stored in plaintext - only this hash is
    # persisted on the AuthSession row, so a DB read never discloses a
    # usable credential.
    return _sha256_hex(token)


def hash_recovery_code(code: str) -> str:
    # Same rationale as hash_refresh_token: recovery codes are one-time
    # bearer credentials and must never be stored in plaintext.
    return _sha256_hex(code.strip().upper())


def create_two_factor_challenge_token(
    subject: uuid.UUID, role: str, challenge_id: uuid.UUID, expires_seconds: int
) -> str:
    return _create_token(
        subject,
        role,
        TokenType.TWO_FACTOR_CHALLENGE,
        timedelta(seconds=expires_seconds),
        jti=challenge_id,
    )


def create_realtime_ticket(subject: uuid.UUID, role: str, expires_seconds: int = 30) -> str:
    return _create_token(
        subject,
        role,
        TokenType.REALTIME,
        timedelta(seconds=expires_seconds),
    )


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError("token is invalid or expired") from exc

    if payload.get("type") != expected_type.value:
        raise TokenError("unexpected token type")

    subject = payload.get("sub")
    if not subject:
        raise TokenError("token is missing a subject")

    try:
        uuid.UUID(str(subject))
    except ValueError as exc:
        raise TokenError("token subject is not a valid account id") from exc

    session_id = payload.get("session_id")
    if session_id is not None:
        try:
            uuid.UUID(str(session_id))
        except ValueError as exc:
            raise TokenError("token session id is not valid") from exc

    return payload
