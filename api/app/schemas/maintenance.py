from typing import Any

from pydantic import BaseModel


class TabellaInfo(BaseModel):
    nome: str
    byte: int
    # Stima del pianificatore, non un `count(*)`: contare per davvero ogni
    # tabella a ogni apertura della pagina costa quanto una scansione completa,
    # per un numero che serve a farsi un'idea.
    righe_stimate: int


class BackupStatusResponse(BaseModel):
    database: str
    byte_database: int
    versione_postgres: str
    revisione_schema: str | None
    versione_strumenti: str
    tabelle: list[TabellaInfo]
    copie_sul_server: list[dict[str, Any]]
    byte_copie: int
    disco: dict[str, int] | None


class RestoreResponse(BaseModel):
    ok: bool
    messaggio: str
    dettaglio: str
    # Vero quando il ripristino è fallito **e** lo stato di prima è stato
    # rimesso: è la differenza fra un tentativo andato male e un magazzino
    # perso.
    stato_precedente_ripristinato: bool
