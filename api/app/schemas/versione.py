from datetime import datetime

from pydantic import BaseModel


class VersioneResponse(BaseModel):
    commit: str | None
    data_commit: str | None
    costruita: str | None
    avviata: datetime
    schema_attuale: str | None
    schema_previsto: str | None
    python: str
    postgresql: str
