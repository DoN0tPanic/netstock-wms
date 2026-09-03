"""Il codice di un'ubicazione, ricavato dal nome.

Il codice serve — è la chiave con cui l'import riconosce un'ubicazione ed è
quello che si scrive sull'etichetta di uno scaffale — ma non c'è ragione di
farlo inventare a chi crea l'ubicazione: «Scaffale A01» dice già tutto, e
`SCAFFALE-A01` si ricava da lì senza chiedere niente.

Due scelte che vale la pena spiegare.

**Si genera solo alla creazione.** Se poi il nome cambia, il codice resta
com'era: è stampato su un'etichetta attaccata a uno scaffale e citato nei file
di import di ieri. Rigenerarlo a ogni rinomina significherebbe che una
correzione di battitura nel nome fa smettere di funzionare l'etichetta.

**Resta modificabile a mano.** Chi ha già una nomenclatura sua (`DEP-A01`)
la scrive e questo codice non entra in gioco: il valore generato è
un'impostazione predefinita, non un'imposizione.
"""
import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

LUNGHEZZA_MASSIMA = 32
RIPIEGO = "UB"


def codice_da_nome(nome: str) -> str:
    """«Scaffale A01» → `SCAFFALE-A01`. Senza accenti, senza spazi, maiuscolo."""
    senza_accenti = "".join(
        c for c in unicodedata.normalize("NFD", nome) if unicodedata.category(c) != "Mn"
    )
    pulito = re.sub(r"[^A-Za-z0-9]+", "-", senza_accenti).strip("-").upper()
    # Un nome fatto solo di simboli («###») lascerebbe una stringa vuota, e il
    # codice è NOT NULL: meglio un ripiego che un errore in faccia a chi stava
    # solo creando uno scaffale.
    return pulito[:LUNGHEZZA_MASSIMA].strip("-") or RIPIEGO


async def codice_libero(db: AsyncSession, modello: type[DeclarativeBase], nome: str) -> str:
    """Il codice ricavato dal nome, con un numero in coda se è già preso.

    Due scaffali che si chiamano davvero uguale esistono (in due magazzini
    diversi), e il codice è unico: `SCAFFALE-A01` e poi `SCAFFALE-A01-2`.
    """
    base = codice_da_nome(nome)
    candidato = base
    for tentativo in range(2, 100):
        esiste = (
            await db.execute(
                select(func.count())
                .select_from(modello)
                .where(func.upper(modello.code) == candidato)  # type: ignore[attr-defined]
            )
        ).scalar_one()
        if not esiste:
            return candidato
        # Il troncamento tiene conto del suffisso, o un nome lungo genererebbe
        # sempre lo stesso codice tagliato e non uscirebbe mai dal ciclo.
        coda = f"-{tentativo}"
        candidato = f"{base[: LUNGHEZZA_MASSIMA - len(coda)].strip('-')}{coda}"
    raise ValueError(f"Nessun codice libero derivabile da «{nome}».")
