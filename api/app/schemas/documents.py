import uuid
from datetime import datetime

from app.schemas.common import OrmModel


class DocumentResponse(OrmModel):
    id: uuid.UUID
    filename: str
    byte_size: int
    pages: int | None
    # Come è stato letto il testo: `testo` dal livello del PDF, `ocr` da una
    # scansione, `nessuno` se non si è trovato niente. Spiega una ricerca che
    # non trova, invece di lasciarla inspiegabile.
    extraction_method: str
    notes: str | None
    delivery_note_id: uuid.UUID | None
    delivery_note_number: str | None = None
    supplier_id: uuid.UUID | None = None
    supplier_name: str | None = None
    # Come è stato riconosciuto il fornitore: `piva` è una prova, `intestazione`
    # è probabile, `manuale` l'ha deciso una persona. Vuoto: non riconosciuto.
    supplier_source: str | None = None
    uploaded_at: datetime


class ContoFornitore(OrmModel):
    """Quanti documenti ha ciascun fornitore, per sfogliare l'archivio."""

    supplier_id: uuid.UUID | None
    supplier_name: str | None
    count: int


class ScegliFornitore(OrmModel):
    supplier_id: uuid.UUID | None
