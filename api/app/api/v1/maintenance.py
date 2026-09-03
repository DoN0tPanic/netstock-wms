"""Copia di sicurezza e ripristino dalle Impostazioni (§11.6)."""
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import text
from starlette.background import BackgroundTask

from app.deps import DbSession, require_role
from app.exceptions import ConflictAppError, ValidationAppError
from app.models.enums import UserRole
from app.models.users import User
from app.schemas.maintenance import (
    BackupStatusResponse,
    RestoreResponse,
    TabellaInfo,
)
from app.services import maintenance
from app.services.audit import write_audit

router = APIRouter(prefix="/maintenance", tags=["maintenance"])

# Le tabelle che dicono qualcosa a chi guarda: quanto pesa il magazzino, non
# quanto pesa ogni indice di sistema.
_TABELLE = """
    SELECT c.relname AS nome,
           pg_total_relation_size(c.oid) AS byte,
           -- `reltuples` vale -1 finché la tabella non è mai stata analizzata:
           -- è «non lo so», non «meno una riga». A schermo diventa un trattino.
           greatest(c.reltuples, 0)::bigint AS righe_stimate
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r'
    ORDER BY pg_total_relation_size(c.oid) DESC
"""


@router.get("/backup", response_model=BackupStatusResponse)
async def stato_backup(
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    """Quanto occupa il database, cosa c'è dentro, e quali copie esistono."""
    dimensione = (
        await db.execute(text("SELECT pg_database_size(current_database())"))
    ).scalar_one()
    versione = (await db.execute(text("SHOW server_version"))).scalar_one()
    revisione = (
        await db.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one_or_none()
    tabelle = [
        TabellaInfo(nome=riga.nome, byte=int(riga.byte), righe_stimate=int(riga.righe_stimate))
        for riga in (await db.execute(text(_TABELLE)))
    ]
    copie = maintenance.copie_sul_server()
    return BackupStatusResponse(
        database=(await db.execute(text("SELECT current_database()"))).scalar_one(),
        byte_database=int(dimensione),
        versione_postgres=versione,
        revisione_schema=revisione,
        versione_strumenti=await maintenance.versione_client(),
        tabelle=tabelle,
        copie_sul_server=copie,
        byte_copie=sum(int(copia["byte"]) for copia in copie),
        disco=maintenance.spazio_disco(),
    )


@router.post("/backup")
async def esegui_backup(
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    """Crea una copia adesso e la consegna a chi l'ha chiesta.

    Non finisce nella cartella del server: quella la riempie il timer
    notturno, e una copia in più sullo stesso disco non protegge da niente.
    Questa arriva sul computer di chi preme il pulsante, che è dove serve il
    giorno in cui il disco non c'è più.
    """
    if maintenance.occupato():
        raise ConflictAppError(
            "C'è già una copia o un ripristino in corso: riprova fra poco."
        )

    cartella = Path(tempfile.mkdtemp(prefix="netstock-backup-"))
    nome = f"netstock-{datetime.now(UTC).astimezone():%Y%m%d-%H%M%S}.dump"
    percorso = cartella / nome

    # Da qui in poi la cartella va rimossa comunque vada: sul successo la
    # toglie il `BackgroundTask` dopo l'invio, su ogni altro esito la si
    # toglie qui — altrimenti resta nel container un file che nessuno guarda
    # più, grande quanto il database.
    try:
        async with maintenance.serratura():
            esito = await maintenance.crea_dump(percorso)
        if not esito.ok:
            raise ValidationAppError(esito.messaggio, details={"dettaglio": esito.dettaglio})

        await write_audit(
            db,
            actor=user,
            actor_username=user.username,
            action="backup.create",
            details={"file": nome, "byte": percorso.stat().st_size},
        )
    except Exception:
        shutil.rmtree(cartella, ignore_errors=True)
        raise
    # `FileResponse` con `background` cancella il temporaneo dopo l'invio: il
    # file non deve restare nel container, e nemmeno sparire prima di essere
    # stato trasmesso.
    return FileResponse(
        percorso,
        media_type="application/octet-stream",
        filename=nome,
        background=BackgroundTask(shutil.rmtree, cartella, ignore_errors=True),
    )


@router.post("/restore", response_model=RestoreResponse)
async def ripristina_backup(
    db: DbSession,
    conferma: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    """Riporta il database al contenuto di una copia caricata.

    L'ordine dei passi è la parte importante:

    1. si controlla la parola di conferma — un ripristino non deve poter
       partire da un clic solo;
    2. si legge l'indice del file **prima** di toccare il database, così un
       file sbagliato viene rifiutato mentre tutto è ancora intatto;
    3. si fa una copia di quello che c'è adesso, perché il ripristino è
       l'unica operazione di questo sistema che cancella davvero dei dati;
    4. si ripristina, e se fallisce si riapplica la copia del punto 3.

    Resta un limite da dire, non da nascondere: durante il ripristino le
    tabelle vengono ricreate, quindi chi sta lavorando in quel momento riceve
    errori. Va fatto quando non c'è nessuno dentro.
    """
    if conferma.strip().upper() != maintenance.CONFERMA:
        raise ValidationAppError(
            f"Per procedere serve la parola «{maintenance.CONFERMA}» nel campo di conferma."
        )
    if maintenance.occupato():
        raise ConflictAppError(
            "C'è già una copia o un ripristino in corso: aspetta che finisca."
        )

    cartella = Path(tempfile.mkdtemp(prefix="netstock-restore-"))
    caricato = cartella / f"caricato-{uuid.uuid4().hex[:8]}.dump"
    scritti = 0
    try:
        with caricato.open("wb") as destinazione:
            while blocco := await file.read(1024 * 1024):
                scritti += len(blocco)
                if scritti > maintenance.LIMITE_RIPRISTINO:
                    raise ValidationAppError("Il file supera il limite consentito.")
                destinazione.write(blocco)

        indice = await maintenance.indice_dump(caricato)
        if not indice.ok:
            raise ValidationAppError(indice.messaggio, details={"dettaglio": indice.dettaglio})

        prima = cartella / "prima-del-ripristino.dump"
        sicurezza = await maintenance.crea_dump(prima)
        if not sicurezza.ok:
            raise ValidationAppError(
                "Non riesco a salvare lo stato attuale, quindi non procedo con il ripristino.",
                details={"dettaglio": sicurezza.dettaglio},
            )

        async with maintenance.serratura():
            esito = await maintenance.ripristina(caricato)
            if not esito.ok:
                rientro = await maintenance.ripristina(prima)
                if not rientro.ok:
                    # Il caso peggiore: il ripristino è fallito **e** lo stato
                    # di prima non è tornato. Il database può essere a metà, e
                    # chi legge deve saperlo dalla risposta, non dai log.
                    return RestoreResponse(
                        ok=False,
                        messaggio=(
                            "Ripristino fallito E stato precedente non ripristinato. "
                            "Il database può essere incompleto: fermare l'applicazione e "
                            "ripristinare a mano una copia (scripts/restore.sh)."
                        ),
                        dettaglio=f"{esito.dettaglio}\n---\n{rientro.dettaglio}",
                        stato_precedente_ripristinato=False,
                    )
                return RestoreResponse(
                    ok=False,
                    messaggio=f"{esito.messaggio} Lo stato di prima è stato rimesso.",
                    dettaglio=esito.dettaglio,
                    stato_precedente_ripristinato=True,
                )

        # L'audit si scrive **dopo**, e nel database appena ripristinato: la
        # riga scritta prima è stata sostituita dal ripristino stesso, insieme
        # a tutto il resto. Registrare l'inizio di un'operazione che cancella
        # il registro è un buon proposito che non lascia traccia.
        await write_audit(
            db,
            actor=None,
            actor_username=user.username,
            action="backup.restore",
            details={"file": file.filename, "byte": scritti},
        )

        return RestoreResponse(
            ok=True,
            messaggio=(
                "Ripristino completato. Le sessioni aperte non valgono più: "
                "rientra con le credenziali che erano valide nella copia."
            ),
            dettaglio="",
            stato_precedente_ripristinato=False,
        )
    finally:
        shutil.rmtree(cartella, ignore_errors=True)
