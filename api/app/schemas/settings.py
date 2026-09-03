from typing import Any

from pydantic import BaseModel

from app.schemas.common import OrmModel


class AppSettingResponse(OrmModel):
    key: str
    value: Any


class AppSettingUpdate(BaseModel):
    value: Any
