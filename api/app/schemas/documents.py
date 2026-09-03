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
    uploaded_at: datetime
