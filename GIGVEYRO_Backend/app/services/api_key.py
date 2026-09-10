import secrets
import uuid
from datetime import UTC, datetime

from app.core.security import hash_api_key
from app.enums.api_key import ApiKeyStatus
from app.models.account import Account
from app.models.api_key import ApiKey
from app.repositories.api_key import ApiKeyRepository

_KEY_PREFIX = "gk_live_"


class ApiKeyNotFoundError(Exception):
    """Covers a missing key and one that exists but isn't visible to the caller."""


class ApiKeyAlreadyRevokedError(Exception):
    """Raised when revoke is attempted on an already-revoked key."""


def generate_raw_api_key() -> str:
    return f"{_KEY_PREFIX}{secrets.token_urlsafe(32)}"


class ApiKeyService:
    def __init__(self, repository: ApiKeyRepository):
        self._keys = repository

    async def create(self, merchant: Account, *, label: str) -> tuple[ApiKey, str]:
        raw_key = generate_raw_api_key()
        api_key = ApiKey(
            merchant_id=merchant.id,
            label=label,
            key_prefix=raw_key[: len(_KEY_PREFIX) + 4],
            key_hash=hash_api_key(raw_key),
            status=ApiKeyStatus.ACTIVE,
        )
        api_key = await self._keys.create(api_key)
        return api_key, raw_key

    async def list_for_merchant(
        self, merchant_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[ApiKey], int]:
        items = await self._keys.list_for_merchant(merchant_id, limit=limit, offset=offset)
        total = await self._keys.count_for_merchant(merchant_id)
        return items, total

    async def revoke(self, merchant_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey:
        api_key = await self._keys.get_by_id_for_update(key_id)
        if api_key is None or api_key.merchant_id != merchant_id:
            raise ApiKeyNotFoundError()
        return await self._revoke(api_key)

    async def revoke_as_owner(self, key_id: uuid.UUID) -> ApiKey:
        api_key = await self._keys.get_by_id_for_update(key_id)
        if api_key is None:
            raise ApiKeyNotFoundError()
        return await self._revoke(api_key)

    async def list_all(self, *, limit: int, offset: int) -> tuple[list[ApiKey], int]:
        items = await self._keys.list_all(limit=limit, offset=offset)
        total = await self._keys.count_all()
        return items, total

    async def _revoke(self, api_key: ApiKey) -> ApiKey:
        if api_key.status == ApiKeyStatus.REVOKED:
            raise ApiKeyAlreadyRevokedError("this key is already revoked")
        api_key.status = ApiKeyStatus.REVOKED
        api_key.revoked_at = datetime.now(UTC)
        return await self._keys.save(api_key)

    async def authenticate(self, raw_key: str) -> ApiKey | None:
        api_key = await self._keys.get_by_hash(hash_api_key(raw_key))
        if api_key is None or api_key.status != ApiKeyStatus.ACTIVE:
            return None
        api_key.last_used_at = datetime.now(UTC)
        await self._keys.save(api_key)
        return api_key
