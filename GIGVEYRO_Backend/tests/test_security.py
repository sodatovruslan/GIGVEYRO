import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_password_differs_from_plaintext():
    assert hash_password("correct-horse-battery") != "correct-horse-battery"


def test_verify_password_accepts_correct_password():
    password_hash = hash_password("correct-horse-battery")
    assert verify_password("correct-horse-battery", password_hash) is True


def test_verify_password_rejects_incorrect_password():
    password_hash = hash_password("correct-horse-battery")
    assert verify_password("wrong-password", password_hash) is False


def test_hash_password_is_salted():
    first = hash_password("correct-horse-battery")
    second = hash_password("correct-horse-battery")
    assert first != second


def test_create_and_decode_access_token():
    account_id = uuid.uuid4()
    token = create_access_token(account_id, "owner")

    payload = decode_token(token, TokenType.ACCESS)

    assert payload["sub"] == str(account_id)
    assert payload["role"] == "owner"
    assert payload["type"] == "access"


def test_create_and_decode_refresh_token():
    account_id = uuid.uuid4()
    token = create_refresh_token(account_id, "owner")

    payload = decode_token(token, TokenType.REFRESH)

    assert payload["sub"] == str(account_id)
    assert payload["type"] == "refresh"


def test_expired_access_token_rejected():
    now = datetime.now(UTC)
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "owner",
        "type": "access",
        "iat": now - timedelta(minutes=20),
        "exp": now - timedelta(minutes=5),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(TokenError):
        decode_token(token, TokenType.ACCESS)


def test_invalid_signature_rejected():
    payload = {
        "sub": str(uuid.uuid4()),
        "role": "owner",
        "type": "access",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "jti": str(uuid.uuid4()),
    }
    other_secret = "a-completely-different-secret-that-is-long-enough"
    token = jwt.encode(payload, other_secret, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(TokenError):
        decode_token(token, TokenType.ACCESS)


def test_refresh_token_rejected_as_access():
    token = create_refresh_token(uuid.uuid4(), "owner")

    with pytest.raises(TokenError):
        decode_token(token, TokenType.ACCESS)


def test_access_token_rejected_as_refresh():
    token = create_access_token(uuid.uuid4(), "owner")

    with pytest.raises(TokenError):
        decode_token(token, TokenType.REFRESH)


def test_invalid_subject_rejected():
    now = datetime.now(UTC)
    payload = {
        "sub": "not-a-uuid",
        "role": "owner",
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": str(uuid.uuid4()),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(TokenError):
        decode_token(token, TokenType.ACCESS)
