import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IdempotencyKey(Base):
    """Un'operazione già eseguita, riconoscibile dalla chiave che l'ha chiesta.

    Vive nella stessa transazione dei movimenti che registra: se l'operazione
    fallisce la chiave sparisce con lei, se riesce restano insieme. È questo
    che rende sicuro ripetere la richiesta — vedi `app/idempotenza.py`.
    """

    __tablename__ = "idempotency_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    route: Mapped[str] = mapped_column(String, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response: Mapped[dict | list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
