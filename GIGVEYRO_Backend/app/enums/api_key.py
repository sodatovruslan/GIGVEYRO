from enum import StrEnum


class ApiKeyStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
