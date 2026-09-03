"""Archivio delle bolle scansionate, con la sua ricerca.

**È una sezione stagna, per scelta.** L'archivio non compare nella ricerca
globale: quella cerca cose che esistono in magazzino — un seriale, un
articolo, un'ubicazione — e risponde con un posto dove andare. Qui invece si
cerca dentro il testo di documenti che possono citare qualunque cosa, comprese
merci mai registrate e clienti che non sono fornitori. Mescolare i due
significherebbe che cercare un seriale restituisce anche ogni bolla che lo
nomina di sfuggita, e la ricerca globale smetterebbe di essere quella cosa
che porta dritto al pezzo.
"""

import re
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, or_, select

from app.deps import CurrentUser, DbSession, require_role
from app.exceptions import NotFoundError, ValidationAppError
from app.models.delivery import DeliveryNote
from app.models.documents import Document
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.common import Page
from app.schemas.documents import DocumentResponse
from app.services import documents_archive
from app.services.audit import write_audit

router = APIRouter(prefix="/documents", tags=["documents"])


async def _con_numero_bolla(db: DbSession, righe: list[Document]) -> list[Document]:
    """Il numero della bolla collegata, per non mostrare un UUID in elenco."""
    identificativi = {r.delivery_note_id for r in righe if r.delivery_note_id}
    numeri: dict[uuid.UUID, str] = {}
    if identificativi:
        risultato = await db.execute(
            select(DeliveryNote.id, DeliveryNote.number).where(
                DeliveryNote.id.in_(identificativi)
            )
        )
        numeri = {riga.id: riga.number for riga in risultato}
    for riga in righe:
        riga.delivery_note_number = (
            numeri.get(riga.delivery_note_id) if riga.delivery_note_id else None
        )
    return righe


@router.get("", response_model=Page[DocumentResponse])
async def elenco(
    db: DbSession,
    user: CurrentUser,
    q: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> Any:
    """L'archivio, cercabile per contenuto.

    Due strade insieme, perché servono a due modi di ricordare. L'indice a
    parole intere trova «DEMO-4471» dentro «n ordine DEMO-4471» ed è veloce anche
    su molti documenti; la ricerca per frammento trova «447» dentro «DEMO-4471»,
    che
    è come si ricorda un numero letto una volta. Le righe trovate dal primo
    vengono prima.
    """
    page_size = min(page_size, 100)
    filtri = []
    ordine = [Document.uploaded_at.desc()]
    if q and q.strip():
        cercato = q.strip()
        corrispondenza = func.to_tsquery("simple", func.quote_literal(cercato) + ":*")
        filtri.append(
            or_(
                Document.search_vector.op("@@")(corrispondenza),
                Document.extracted_text.ilike(f"%{cercato}%"),
                Document.filename.ilike(f"%{cercato}%"),
            )
        )
        ordine = [Document.search_vector.op("@@")(corrispondenza).desc(), *ordine]

    totale = (
        await db.execute(select(func.count()).select_from(Document).where(*filtri))
    ).scalar_one()
    righe = list(
        (
            await db.execute(
                select(Document)
                .where(*filtri)
                .order_by(*ordine)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return Page(
        items=await _con_numero_bolla(db, righe),
        total=int(totale),
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=DocumentResponse, status_code=201)
async def carica(
    db: DbSession,
    file: UploadFile = File(...),
    note: str | None = Form(default=None),
    delivery_note_id: uuid.UUID | None = Form(default=None),
    user: User = Depends(require_role(UserRole.operator)),
) -> Any:
    """Archivia un PDF e ne indicizza il contenuto."""
    dati = await file.read()
    testo, metodo, pagine = documents_archive.leggi(dati, file.content_type)
    firma = documents_archive.impronta(dati)

    # Lo stesso file caricato due volte è lo stesso documento, anche con un
    # nome diverso: chi scansiona ricarica per sbaglio più spesso di quanto
    # ammetta, e due copie della stessa bolla sono peggio di zero.
    esistente = (
        await db.execute(select(Document).where(Document.sha256 == firma))
    ).scalar_one_or_none()
    if esistente is not None:
        raise ValidationAppError(
            f"Questo documento è già in archivio come «{esistente.filename}».",
            details={"id": str(esistente.id)},
        )

    documento = Document(
        filename=(file.filename or "documento.pdf")[:255],
        mime_type="application/pdf",
        byte_size=len(dati),
        sha256=firma,
        pages=pagine,
        content=dati,
        extracted_text=testo,
        extraction_method=metodo,
        notes=(note or None),
        delivery_note_id=delivery_note_id,
        uploaded_by=user.id,
    )
    db.add(documento)
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="document.upload",
        entity_type="document",
        entity_id=str(documento.id),
        # Il nome del file e quanto pesa, non cosa c'era scritto: il registro
        # di sicurezza non è il posto dove far finire il contenuto di una
        # bolla (§7.5).
        details={"file": documento.filename, "byte": documento.byte_size, "lettura": metodo},
    )
    return (await _con_numero_bolla(db, [documento]))[0]


def _disposizione(filename: str, *, allegato: bool) -> str:
    """Il nome del file dentro un'intestazione HTTP, senza fidarsi del nome.

    Il nome arriva dal caricamento: può contenere virgolette o un a capo, che
    spezzerebbero l'intestazione, o caratteri fuori da latin-1, l'unica
    codifica che un'intestazione ammette («bolla città.pdf» passa, un nome in
    cirillico farebbe fallire la risposta con un errore 500). Si manda quindi
    un nome ripulito come ripiego e quello vero in `filename*`, che i browser
    preferiscono (RFC 6266).
    """
    ripiego = re.sub(r"[^A-Za-z0-9._ -]", "_", filename).strip() or "documento.pdf"
    tipo = "attachment" if allegato else "inline"
    return f"{tipo}; filename=\"{ripiego}\"; filename*=UTF-8\'\'{quote(filename)}"


@router.get("/{documento_id}/file")
async def file_originale(
    documento_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    scarica: bool = False,
) -> Any:
    """Il PDF originale: da guardare nel browser, o da salvare con `?scarica=1`.

    Sono due gesti diversi e la differenza la decide il server, non il link:
    con `attachment` il browser salva una copia anche quando ha un lettore di
    PDF incorporato, che altrimenti si limita ad aprirlo in una scheda.
    """
    documento = await db.get(Document, documento_id)
    if documento is None:
        raise NotFoundError("Documento non trovato.", details={"id": str(documento_id)})
    return Response(
        content=documento.content,
        media_type="application/pdf",
        headers={"Content-Disposition": _disposizione(documento.filename, allegato=scarica)},
    )


@router.get("/{documento_id}/testo")
async def testo_estratto(documento_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Any:
    """Il testo su cui si cerca.

    Serve quando una ricerca non trova quello che si sa essere lì: leggendo
    ciò che il sistema ha davvero letto si capisce se il problema è l'OCR o
    la ricerca.
    """
    documento = await db.get(Document, documento_id)
    if documento is None:
        raise NotFoundError("Documento non trovato.", details={"id": str(documento_id)})
    return {
        "id": str(documento.id),
        "filename": documento.filename,
        "extraction_method": documento.extraction_method,
        "text": documento.extracted_text,
    }


@router.delete("/{documento_id}", status_code=204)
async def elimina(
    documento_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> None:
    """Toglie un documento dall'archivio.

    Riservata agli amministratori: un documento è una prova di cosa è
    arrivato, e cancellarlo non è un'operazione da fare di passaggio.
    """
    documento = await db.get(Document, documento_id)
    if documento is None:
        raise NotFoundError("Documento non trovato.", details={"id": str(documento_id)})
    nome = documento.filename
    await db.execute(sql_delete(Document).where(Document.id == documento_id))
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="document.delete",
        entity_type="document",
        entity_id=str(documento_id),
        details={"file": nome},
    )
