from pydantic import BaseModel, ConfigDict

from app.enums.wallet import Currency
from app.schemas.common import Money


class MerchantWalletRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    currency: Currency
    available_balance: Money
