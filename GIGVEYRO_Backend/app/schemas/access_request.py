from pydantic import BaseModel, Field, field_validator


class AccessRequestCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    contact: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("full_name", "contact")
    @classmethod
    def _strip_and_require_non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class AccessRequestAck(BaseModel):
    status: str = "received"
