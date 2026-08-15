from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TrafficRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    is_enabled: bool
    enabled_at: datetime | None
    disabled_at: datetime | None
