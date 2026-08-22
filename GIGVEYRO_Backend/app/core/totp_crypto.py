"""Encryption at rest for TOTP secrets.

Ciphertext is stored as "<key_version>:<fernet_token>" so a future key
rotation can add a new version without invalidating already-stored
secrets - old ciphertext keeps decrypting via its recorded version while
new encryptions move to the current version.
"""

from cryptography.fernet import Fernet

from app.core.config import settings

_CURRENT_KEY_VERSION = 1


def _fernet_for_version(version: int) -> Fernet:
    if version == 1:
        return Fernet(settings.TOTP_ENCRYPTION_KEY.encode("utf-8"))
    raise ValueError(f"unknown TOTP encryption key version: {version}")


def encrypt_totp_secret(plaintext_secret: str) -> str:
    token = _fernet_for_version(_CURRENT_KEY_VERSION).encrypt(plaintext_secret.encode("utf-8"))
    return f"{_CURRENT_KEY_VERSION}:{token.decode('utf-8')}"


def decrypt_totp_secret(ciphertext: str) -> str:
    version_str, separator, token = ciphertext.partition(":")
    if not separator:
        raise ValueError("malformed TOTP ciphertext: missing key version prefix")
    fernet = _fernet_for_version(int(version_str))
    return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
