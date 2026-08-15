from typing import Annotated

from pydantic import Field

from app.core.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH

PasswordStr = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)]
