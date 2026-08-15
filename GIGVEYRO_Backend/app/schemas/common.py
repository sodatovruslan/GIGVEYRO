from decimal import Decimal
from typing import Annotated

from pydantic import Field, PlainSerializer

from app.core.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH

PasswordStr = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)]

# Money is always Decimal end-to-end (never float). Serialized to JSON as a
# fixed-point string (e.g. "500.00000000") so clients never lose precision
# or hit scientific notation.
Money = Annotated[
    Decimal, PlainSerializer(lambda v: format(v, "f"), return_type=str, when_used="json")
]
