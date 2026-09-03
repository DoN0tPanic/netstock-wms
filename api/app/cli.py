"""Operational CLI (§6.6): `python -m app.cli <command>`."""

import asyncio
import pathlib
import sys
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.db import AsyncSessionLocal
from app.exceptions import AppError
from app.models.enums import UserRole
from app.models.users import User
from app.services.audit import write_audit
from app.services.imports import (
    RIFERIMENTO_INIZIALE,
    importa_catalogo,
    importa_giacenza,
    leggi_csv,
)


async def _reconcile(fix: bool) -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                "SELECT catalog_item_id, location_id, qty_ledger, qty_projection "
                "FROM v_reconciliation_errors"
            )
        )
        rows = result.mappings().all()

        if not rows:
            print("Nessuna divergenza tra ledger e proiezione delle unità.")
            return 0

        print(f"Trovate {len(rows)} divergenze tra ledger e proiezione:")
        for row in rows:
            print(
                f"  articolo={row['catalog_item_id']} ubicazione={row['location_id']} "
                f"ledger={row['qty_ledger']} proiezione={row['qty_projection']}"
            )

        if fix:
            # The ledger always wins: rebuild stock_units.location_id/status
            # from stock_movements per catalog item involved in a divergence.
            item_ids = {row["catalog_item_id"] for row in rows}
            for item_id in item_ids:
                await db.execute(
                    text(
                        """
                        WITH last_movement AS (
                            SELECT DISTINCT ON (stock_unit_id)
                                stock_unit_id, location_to_id, type
                            FROM stock_movements
                            WHERE catalog_item_id = :item_id AND stock_unit_id IS NOT NULL
                            ORDER BY stock_unit_id, occurred_at DESC, created_at DESC
                        )
                        UPDATE stock_units su
                        SET location_id = lm.location_to_id
                        FROM last_movement lm
                        WHERE su.id = lm.stock_unit_id
                        """
                    ),
                    {"item_id": item_id},
                )
            await write_audit(
                db,
                actor=None,
                actor_username="system",
                action="stock.reconcile_fix",
                details={"affected_items": [str(i) for i in item_ids]},
            )
            await db.commit()
            print("Proiezione ricostruita dal ledger. Il ledger non è mai stato modificato.")
        return 1


async def _seed_info() -> int:
    print(
        "I dati di seed sono applicati dalla migration Alembic 0002_seed.py.\n"
        "Eseguire 'alembic upgrade head' (già incluso nell'avvio del container)."
    )
    return 0


async def _attore(db, username: str | None) -> User:
    """Chi firma i movimenti dell'import.

    Non c'è una sessione: l'import è un'operazione da riga di comando. La
    firma però è obbligatoria — nel ledger ogni movimento ha un autore — e
    dev'essere un utente vero, non un segnaposto: `--utente` lo sceglie,
    altrimenti si usa il primo amministratore attivo.
    """
    if username:
        stmt = select(User).where(User.username == username, User.deleted_at.is_(None))
    else:
        stmt = (
            select(User)
            .where(
                User.role == UserRole.admin,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
            .order_by(User.created_at)
        )
    utente = (await db.execute(stmt)).scalars().first()
    if utente is None:
        raise SystemExit(f"Utente «{username}» non trovato." if username
                         else "Nessun amministratore attivo a cui attribuire l'import.")
    return utente


async def _importa(genere: str, percorso: str, argomenti: list[str]) -> int:
    """Legge, esegue, e scrive solo se glielo si chiede.

    La prova a vuoto non è una simulazione: fa il lavoro per davvero dentro
    una transazione e poi la annulla. Simulare avrebbe voluto dire riscrivere
    a parte i controlli sui seriali doppi e sul formato — cioè controllare
    con codice diverso da quello che poi esegue, che è il modo classico di
    avere una prova verde e un import rotto.
    """
    applica = "--applica" in argomenti
    conferma = "--conferma-anomalie" in argomenti
    utente = next((a.split("=", 1)[1] for a in argomenti if a.startswith("--utente=")), None)
    data = next((a.split("=", 1)[1] for a in argomenti if a.startswith("--data=")), None)

    file = pathlib.Path(percorso)
    if not file.is_file():
        print(f"File non trovato: {percorso}")
        return 1
    righe = leggi_csv(file.read_text(encoding="utf-8-sig"))
    if not righe:
        print("Il file non contiene righe.")
        return 1
    print(f"{len(righe)} righe lette da {file.name}.\n")

    quando = None
    if data:
        try:
            quando = datetime.fromisoformat(data).replace(tzinfo=UTC)
        except ValueError:
            print(f"Data non valida: «{data}». Formato atteso: 2026-09-01.")
            return 1

    async with AsyncSessionLocal() as db:
        try:
            if genere == "catalogo":
                rapporto = await importa_catalogo(db, righe)
            else:
                attore = await _attore(db, utente)
                print(f"I movimenti verranno firmati da «{attore.username}».")
                rapporto = await importa_giacenza(
                    db, righe, performer=attore, quando=quando, conferma_anomalie=conferma
                )
        except AppError as rifiuto:
            # Le regole del magazzino valgono anche qui: un seriale già a
            # magazzino, una data nel futuro, una quantità che non torna. Il
            # messaggio è già scritto per una persona — quello che non deve
            # succedere è che arrivi come traccia di stack, e che qualcuno si
            # chieda se metà import sia passato lo stesso.
            await db.rollback()
            print(f"  ERRORE   {rifiuto.message}")
            print("\n  Niente è stato scritto: correggi il file e rilancia.")
            return 1

        if rapporto.valido and applica:
            await db.commit()
            rapporto.stampa(applicato=True)
            if genere == "giacenza":
                print(f"  Riferimento dei movimenti: {RIFERIMENTO_INIZIALE}")
            return 0

        # Anche quando è tutto a posto: senza --applica non si scrive.
        await db.rollback()
        rapporto.stampa(applicato=False)
        if not rapporto.valido:
            print("\n  Niente è stato scritto: correggi il file e rilancia.")
            return 1
        print("\n  Prova a vuoto: niente è stato scritto. Rilancia con --applica.")
        return 0


USO = """Uso: python -m app.cli <comando> [opzioni]

  reconcile [--fix]        confronta ledger e proiezione delle unità
  seed                     dove stanno i dati iniziali
  import-catalogo FILE     crea gli articoli che mancano
  import-giacenza FILE     registra la giacenza di partenza come movimenti

  Gli import non scrivono niente finché non si passa --applica.
  Opzioni: --applica  --utente=NOME  --data=AAAA-MM-GG  --conferma-anomalie
"""


def main() -> None:
    if len(sys.argv) < 2:
        print(USO)
        sys.exit(1)

    command = sys.argv[1]
    if command == "reconcile":
        fix = "--fix" in sys.argv
        exit_code = asyncio.run(_reconcile(fix))
    elif command == "seed":
        exit_code = asyncio.run(_seed_info())
    elif command in ("import-catalogo", "import-giacenza"):
        if len(sys.argv) < 3:
            print(f"Manca il file: python -m app.cli {command} FILE.csv")
            sys.exit(1)
        genere = "catalogo" if command == "import-catalogo" else "giacenza"
        exit_code = asyncio.run(_importa(genere, sys.argv[2], sys.argv[3:]))
    else:
        print(f"Comando sconosciuto: {command}\n")
        print(USO)
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
