from datetime import datetime

from pydantic import BaseModel


class AvvisoResponse(BaseModel):
    codice: str
    gravita: str
    titolo: str
    dettaglio: str


class AvvisiResponse(BaseModel):
    ora_server: datetime
    avvisi: list[AvvisoResponse]
