"""Da quale fornitore arriva una bolla, letto dalla bolla stessa.

**Il principio è quello di tutta la lettura automatica: il sistema non
inventa un fornitore, lo riconosce fra quelli che esistono già.** Non c'è
nessun passaggio in cui un modello propone un nome di società: si prendono i
fornitori in anagrafica e si guarda quale di quelli è scritto nel documento.
Un fornitore sbagliato su una bolla archiviata è peggio di nessun fornitore —
il secondo si vede a colpo d'occhio, il primo no.

Due prove, in quest'ordine:

1. **La partita IVA.** Se la partita IVA del fornitore è stampata nel
   documento, è lui: undici cifre non capitano per caso. È il riconoscimento
   di cui ci si può fidare senza guardare.
2. **Il nome nella testata.** Solo nella prima parte del documento, dove sta
   la carta intestata di chi la bolla l'ha emessa. Più giù il nome di
   un'azienda compare per mille motivi — «Cisco» è scritto su ogni riga di
   una bolla di switch Cisco, e il fornitore è il distributore che li ha
   venduti, non Cisco.

Se combaciano due fornitori diversi, non se ne sceglie nessuno: un archivio
con un fornitore in meno da assegnare a mano è un archivio corretto, uno con
un fornitore sbagliato assegnato da solo è un archivio da rifare.
"""

import re
import unicodedata
import uuid
from dataclasses import dataclass

# Quanta parte del documento è «testata». Il confine vero non è un numero di
# caratteri ma il titolo del documento: sopra c'è la carta intestata di chi la
# bolla l'ha emessa, sotto comincia la bolla — e con lei le righe della merce,
# dove i nomi delle aziende compaiono per tutt'altro motivo. Le due misure qui
# sono il tetto per quando il titolo non si trova.
INTESTAZIONE = 600
RIGHE_TESTATA = 12

# Le parole con cui una bolla annuncia sé stessa. La prima riga che ne
# contiene una chiude la testata.
_TITOLO = re.compile(
    r"\b(DOCUMENTO DI TRASPORTO|DDT|D D T|BOLLA|PACKING LIST|FATTURA|"
    r"DELIVERY NOTE|LIEFERSCHEIN)\b"
)

# Un nome troppo corto non è una prova: «BIT», «ACE», «TEC» capitano dentro
# altre parole e come sigle di reparto.
LUNGHEZZA_MINIMA_NOME = 4

# Forme societarie: tolte dal nome prima del confronto, perché nel documento
# possono essere scritte in dieci modi diversi («S.p.A.», «SPA», «S.P.A.»)
# mentre in anagrafica sono scritte in uno solo.
_FORME = {
    "SPA", "SRL", "SRLS", "SAS", "SNC", "SCARL", "SCRL", "SS",
    "LTD", "LIMITED", "GMBH", "AG", "BV", "NV", "SA", "INC", "CORP",
    "CO", "C", "SOCIETA", "PER", "AZIONI", "ITALIA", "ITALY", "GROUP",
}


@dataclass(frozen=True)
class Fornitore:
    """Il minimo che serve al riconoscimento: chi è e come si riconosce."""

    id: uuid.UUID
    name: str
    vat_number: str | None


def normalizza(testo: str) -> str:
    """Maiuscolo, senza accenti e con un solo spazio fra le parole.

    Serve a confrontare «Rossi & Figli S.r.l.» con «ROSSI E FIGLI SRL» come se
    fossero la stessa scritta, che è quello che sono. Tutto ciò che non è
    lettera o cifra diventa uno spazio, così una parola resta delimitata da
    spazi e la si può cercare senza agganciare pezzi di parole più lunghe.
    """
    senza_accenti = unicodedata.normalize("NFKD", testo)
    senza_accenti = "".join(c for c in senza_accenti if not unicodedata.combining(c))
    # «&» diventa «E»: la stessa ditta è «Rossi & Figli» in anagrafica e «ROSSI
    # E FIGLI» sulla carta intestata, e sono la stessa ditta.
    senza_accenti = senza_accenti.upper().replace("&", " E ")
    return " " + re.sub(r"[^A-Z0-9]+", " ", senza_accenti).strip() + " "


def testata(testo: str) -> str:
    """La parte alta del documento, quella della carta intestata.

    Si ferma alla riga che annuncia il documento («Documento di trasporto»,
    «D.D.T. n. …»): da lì in giù c'è la bolla, e cercarci dentro il nome di
    un'azienda vuol dire trovare il costruttore di quello che è stato
    consegnato invece di chi l'ha consegnato. È il caso che si vede subito
    provando: una bolla di «Tecno Forniture» con dieci righe di switch Cisco
    finiva a Cisco, con sicurezza e sbagliando.
    """
    righe: list[str] = []
    for riga in testo.splitlines():
        if not riga.strip():
            continue
        if _TITOLO.search(normalizza(riga)):
            break
        righe.append(riga)
        if len(righe) >= RIGHE_TESTATA:
            break
    return "\n".join(righe)[:INTESTAZIONE]


def _cifre_piva(valore: str | None) -> str | None:
    """Le undici cifre di una partita IVA italiana, senza «IT», punti e spazi."""
    if not valore:
        return None
    cifre = re.sub(r"[^0-9]", "", valore)
    return cifre if len(cifre) == 11 else None


def parole_identificative(nome: str) -> set[str]:
    """Le parole di un nome che lo identificano davvero.

    Fuori le forme societarie e le lettere singole: «S.r.l.» diventa «S R L»
    una volta tolta la punteggiatura, e cercare quelle tre lettere dentro un
    documento non dice niente su chi l'ha emesso.
    """
    return {p for p in normalizza(nome).split() if p not in _FORME and len(p) > 1}


def riconosci(testo: str, fornitori: list[Fornitore]) -> tuple[uuid.UUID, str] | None:
    """Il fornitore di questo documento e come lo si è capito, o niente."""
    if not testo.strip() or not fornitori:
        return None

    normalizzato = normalizza(testo)

    per_piva = [
        f for f in fornitori
        if (cifre := _cifre_piva(f.vat_number)) and f" {cifre} " in normalizzato
    ]
    if len(per_piva) == 1:
        return per_piva[0].id, "piva"
    if per_piva:
        # Due fornitori con la stessa partita IVA in anagrafica: è un problema
        # dell'anagrafica, e non lo si risolve tirando a indovinare qui.
        return None

    parte_alta = normalizza(testata(testo))
    per_nome = []
    for fornitore in fornitori:
        parole = parole_identificative(fornitore.name)
        # Tutte le parole del nome, ciascuna intera, non per forza vicine: fra
        # «Rossi» e «Figli» il documento può avere una «&», una «E» o un a
        # capo, e sono la stessa ditta. Almeno una dev'essere lunga: un nome
        # fatto di sole parole corte non è una prova di niente.
        if not parole or not any(len(p) >= LUNGHEZZA_MINIMA_NOME for p in parole):
            continue
        if all(f" {parola} " in parte_alta for parola in parole):
            per_nome.append(fornitore)
    if len(per_nome) == 1:
        return per_nome[0].id, "intestazione"
    return None
