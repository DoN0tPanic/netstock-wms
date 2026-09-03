import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    FetchedValue,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Document(Base):
    """Una bolla scansionata, conservata perché qualcuno ha deciso di conservarla.

    Il contenuto sta nella colonna `content` e non su un volume: il backup
    notturno copia il database, e un archivio su disco risulterebbe vuoto al
    primo ripristino — con i riferimenti ancora al loro posto (§0004).
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    pages: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extraction_method: Mapped[str] = mapped_column(Text, nullable=False, default="none")
    notes: Mapped[str | None] = mapped_column(Text)
    delivery_note_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("delivery_notes.id", ondelete="SET NULL")
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Colonna **generata dal database** (§0004): si può leggere e cercarci
    # dentro, non scrivere. `FetchedValue` è la dichiarazione di questo — la
    # tiene fuori da INSERT e UPDATE — senza ripetere qui l'espressione che
    # la calcola, che vive nella migrazione e non deve esistere in due posti.
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR, server_default=FetchedValue(), nullable=True
    )

    # Il numero della bolla collegata non è una colonna: l'elenco lo calcola
    # e lo appoggia qui, come fa /movements con i codici leggibili.
    delivery_note_number = None
