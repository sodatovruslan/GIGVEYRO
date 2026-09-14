from enum import StrEnum


class UserRole(StrEnum):
    OWNER = "owner"
    USER = "user"
    MERCHANT = "merchant"
    TEAM_LEAD = "team_lead"
