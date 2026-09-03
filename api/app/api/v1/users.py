import secrets
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DbSession, require_role
from app.exceptions import NotFoundError, ValidationAppError
from app.models.enums import UserRole
from app.models.users import Session, User
from app.schemas.common import Page
from app.schemas.users import (
    ResetPasswordResponse,
    UserCreate,
    UserDeleteResponse,
    UserResponse,
    UserUpdate,
)
from app.services.audit import write_audit
from app.services.auth.blocklist import is_common_password
from app.services.auth.password import hash_password

router = APIRouter(prefix="/users", tags=["users"])

# Ogni colonna che punta a `users` con ON DELETE RESTRICT, cioè ogni riga che
# impedisce fisicamente di togliere l'utente dal database. `sessions` non c'è:
# è l'unica in CASCADE, e sparire insieme all'account è esattamente ciò che
# deve fare.
#
# L'elenco è scritto a mano ma non è sulla fiducia: `tests/test_user_delete.py`
# lo confronta con i vincoli davvero presenti nel catalogo di PostgreSQL, così
# una nuova tabella che punti a `users` fa fallire il test invece di far
# fallire l'eliminazione in produzione.
USER_REFERENCES: tuple[tuple[str, str], ...] = (
    ("audit_log", "actor_id"),
    ("stock_movements", "performed_by"),
    ("delivery_notes", "received_by"),
    ("reservations", "created_by"),
    ("extraction_templates", "created_by"),
    ("extraction_runs", "user_id"),
    ("app_settings", "updated_by"),
)

# Gli stessi nomi che l'amministratore legge a schermo (il gemello sta in
# `web/src/pages/Admin/index.tsx`): un rifiuto che parla di `stock_movements`
# non dice a chi lo legge perché quell'account non si può togliere.
# Singolare e plurale, perché il messaggio dice sempre un numero e «1
# operazioni» è la firma di una frase costruita a pezzi.
TRACE_LABELS: dict[str, tuple[str, str]] = {
    "audit_log": ("operazione nel registro di sicurezza", "operazioni nel registro di sicurezza"),
    "stock_movements": ("movimento di magazzino", "movimenti di magazzino"),
    "delivery_notes": ("bolla registrata", "bolle registrate"),
    "reservations": ("prenotazione", "prenotazioni"),
    "extraction_templates": ("template di estrazione", "template di estrazione"),
    "extraction_runs": ("lettura di documenti", "letture di documenti"),
    "app_settings": ("impostazione modificata", "impostazioni modificate"),
}


def describe_traces(traces: dict[str, int]) -> str:
    pezzi = []
    for table, count in traces.items():
        singolare, plurale = TRACE_LABELS.get(table, (table, table))
        pezzi.append(f"{count} {singolare if count == 1 else plurale}")
    return ", ".join(pezzi)


async def _traces(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """Quante righe di registro portano la firma di questo utente, per tabella.

    I nomi di tabella e colonna vengono da `USER_REFERENCES`, che è una
    costante di questo modulo: nessun valore di richiesta entra nell'SQL.
    """
    found: dict[str, int] = {}
    for table, column in USER_REFERENCES:
        stmt = text(f"SELECT count(*) FROM {table} WHERE {column} = :user_id")  # noqa: S608
        count = (await db.execute(stmt, {"user_id": user_id})).scalar_one()
        if count:
            found[table] = int(count)
    return found


async def _load(db: AsyncSession, user_id: uuid.UUID) -> User:
    target = await db.get(User, user_id)
    if target is None or target.deleted_at is not None:
        raise NotFoundError("Utente non trovato.", details={"id": str(user_id)})
    return target


async def _purgeable_ids(db: AsyncSession) -> set[uuid.UUID]:
    """Gli account chiusi che nessuna riga di registro cita.

    Sono gli unici che si possono ancora togliere dal database. Una query
    sola per tutto l'elenco invece di sette per riga: gli account chiusi sono
    pochi e `EXISTS` si ferma alla prima riga trovata.
    """
    conditions = " OR ".join(
        f"EXISTS (SELECT 1 FROM {table} WHERE {column} = u.id)"
        for table, column in USER_REFERENCES
    )
    stmt = text(  # noqa: S608
        f"SELECT u.id FROM users u WHERE u.deleted_at IS NOT NULL AND NOT ({conditions})"
    )
    return {row[0] for row in await db.execute(stmt)}


async def _other_admins(db: AsyncSession, user_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(User).where(
        User.role == UserRole.admin,
        User.is_active.is_(True),
        User.deleted_at.is_(None),
        User.id != user_id,
    )
    return int((await db.execute(stmt)).scalar_one())


@router.get("", response_model=Page[UserResponse])
async def list_users(
    db: DbSession, page: int = 1, page_size: int = 50, include_deleted: bool = False,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    page_size = min(page_size, 200)
    where = () if include_deleted else (User.deleted_at.is_(None),)
    total = (await db.execute(select(func.count()).select_from(User).where(*where))).scalar_one()
    stmt = (
        select(User).where(*where)
        .order_by(User.deleted_at.is_(None).desc(), User.username)
        .offset((page - 1) * page_size).limit(page_size)
    )
    items = list((await db.execute(stmt)).scalars().all())
    # Serve a chi amministra per sapere, prima di premere, se «elimina
    # definitivamente» è ancora possibile per quella riga o se quell'account
    # resterà nel registro per sempre.
    purgeable = await _purgeable_ids(db) if include_deleted else set()
    for item in items:
        item.can_purge = item.deleted_at is not None and item.id in purgeable
    return Page(items=items, total=int(total), page=page, page_size=page_size)


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    payload: UserCreate,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    if is_common_password(payload.initial_password):
        raise ValidationAppError("La password iniziale scelta è troppo comune.")
    # Il nome utente di un account eliminato resta occupato: le righe di
    # registro lo citano per nome, e riassegnarlo a una persona diversa
    # renderebbe illeggibile chi ha fatto cosa. Meglio dirlo qui che lasciare
    # affiorare un vincolo di unicità dal database.
    stmt = select(User).where(User.username == payload.username, User.deleted_at.is_not(None))
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise ValidationAppError(
            f"Il nome utente «{payload.username}» apparteneva a un account eliminato e resta "
            "riservato a lui nel registro. Ripristina quell'account, oppure eliminalo "
            "definitivamente se non ha lasciato tracce, oppure scegli un altro nome."
        )
    new_user = User(
        username=payload.username,
        full_name=payload.full_name,
        email=payload.email,
        role=payload.role,
        password_hash=hash_password(payload.initial_password),
        must_change_password=True,
    )
    db.add(new_user)
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="user.create",
        entity_type="user",
        entity_id=str(new_user.id),
        details={"username": new_user.username, "role": new_user.role.value},
    )
    return new_user


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    target = await _load(db, user_id)
    changes = payload.model_dump(exclude_unset=True)
    # Togliersi da soli l'ultimo accesso amministrativo non è un'operazione da
    # confermare: è una porta che si chiude dall'esterno, e non c'è nessuno
    # dentro a riaprirla.
    disattiva = changes.get("is_active") is False
    declassa = changes.get("role") is not None and changes["role"] != UserRole.admin
    ultimo = target.role == UserRole.admin and (disattiva or declassa)
    if ultimo and await _other_admins(db, user_id) == 0:
        raise ValidationAppError(
            "È l'ultimo amministratore attivo: nomina prima un altro amministratore."
        )
    for key, value in changes.items():
        setattr(target, key, value)
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="user.update",
        entity_type="user",
        entity_id=str(target.id),
        details={"changed_fields": changes},
    )
    return target


@router.delete("/{user_id}", response_model=UserDeleteResponse)
async def delete_user(
    user_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    """Chiude un account: accesso tolto, sessioni chiuse, fuori dall'elenco.

    Chiudere e basta, senza togliere niente dal database, è l'unica forma che
    vale sempre — chi ha firmato una riga di registro non si può rimuovere
    (§4.2: quelle righe lo referenziano con ON DELETE RESTRICT e sono
    append-only per trigger) — ed è anche l'unica che si può disfare. Chi non
    ha lasciato tracce si toglie davvero, ma con un secondo gesto esplicito:
    `DELETE /users/{id}/permanent`. Prima le due cose stavano in un'unica
    chiamata che sceglieva da sé, e l'account senza storia spariva senza
    comparire fra gli eliminati: dall'esterno era indistinguibile da
    un'eliminazione non riuscita.
    """
    target = await _load(db, user_id)
    # Chi elimina è per forza un amministratore attivo e diverso dal bersaglio,
    # quindi un amministratore resta sempre: qui basta il divieto di eliminare
    # sé stessi. Il caso «ultimo amministratore» si presenta invece davvero
    # nell'aggiornamento, dove uno può declassare o disattivare sé stesso.
    if target.id == user.id:
        raise ValidationAppError("Non puoi eliminare l'account con cui sei entrato.")

    traces = await _traces(db, user_id)
    username = target.username

    await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )

    target.deleted_at = datetime.now(UTC)
    target.is_active = False
    target.password_hash = None
    target.must_change_password = True
    await db.flush()

    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="user.delete",
        entity_type="user",
        entity_id=str(user_id),
        details={"username": username, "traces": traces},
    )
    return UserDeleteResponse(
        removed=False, username=username, traces=traces, purgeable=not traces
    )


@router.delete("/{user_id}/permanent", response_model=UserDeleteResponse)
async def purge_user(
    user_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    """Toglie dal database un account già chiuso che non ha lasciato tracce.

    Si applica solo a un account già eliminato: la rimozione definitiva non
    si annulla, e passare dalla chiusura significa che chi la esegue ha
    davanti la riga, il suo stato e il fatto che non è citata da nessuna
    parte. Il nome utente torna libero, perché non resta nessuna riga che lo
    citi.
    """
    target = await db.get(User, user_id)
    if target is None:
        raise NotFoundError("Utente non trovato.", details={"id": str(user_id)})
    if target.deleted_at is None:
        raise ValidationAppError(
            "Questo account è ancora attivo: eliminalo prima, poi potrai toglierlo del tutto."
        )

    traces = await _traces(db, user_id)
    if traces:
        raise ValidationAppError(
            f"«{target.username}» non si può togliere dal database: il registro porta la sua "
            f"firma su {describe_traces(traces)}. Quelle righe non si modificano e non si "
            "cancellano (§4.2), quindi l'account resta come firma leggibile.",
            details={"traces": traces},
        )

    username = target.username
    await db.execute(delete(Session).where(Session.user_id == user_id))
    await db.delete(target)
    await db.flush()

    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="user.purge",
        entity_type="user",
        entity_id=str(user_id),
        details={"username": username},
    )
    return UserDeleteResponse(removed=True, username=username, traces={}, purgeable=False)


@router.post("/{user_id}/restore", response_model=ResetPasswordResponse)
async def restore_user(
    user_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    """Riapre un account chiuso, con una password nuova.

    La chiusura cancella la password: non c'è niente da ripristinare, e
    l'unico modo onesto di rimettere dentro qualcuno è dargli una password
    temporanea da cambiare subito, come per una reimpostazione.
    """
    target = await db.get(User, user_id)
    if target is None:
        raise NotFoundError("Utente non trovato.", details={"id": str(user_id)})
    if target.deleted_at is None:
        raise ValidationAppError("Questo utente non è eliminato.")
    temporary_password = secrets.token_urlsafe(12)
    target.deleted_at = None
    target.is_active = True
    target.password_hash = hash_password(temporary_password)
    target.must_change_password = True
    target.failed_attempts = 0
    target.locked_until = None
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="user.restore",
        entity_type="user",
        entity_id=str(target.id),
        details={"username": target.username},
    )
    return ResetPasswordResponse(temporary_password=temporary_password)


@router.post("/{user_id}/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    user_id: uuid.UUID,
    db: DbSession,
    user: User = Depends(require_role(UserRole.admin)),
) -> Any:
    target = await _load(db, user_id)
    temporary_password = secrets.token_urlsafe(12)
    target.password_hash = hash_password(temporary_password)
    target.must_change_password = True
    await db.flush()
    await write_audit(
        db,
        actor=user,
        actor_username=user.username,
        action="user.reset_password",
        entity_type="user",
        entity_id=str(target.id),
        details={},
    )
    return ResetPasswordResponse(temporary_password=temporary_password)
