"""Da quale fornitore arriva una bolla, riconosciuto dal testo della bolla.

I nomi e le partite IVA qui sono inventati: un fornitore vero non entra fra i
sorgenti (§7.5).
"""

import uuid

import pytest

from app.services.fornitori_bolle import Fornitore, riconosci

NORD = Fornitore(id=uuid.uuid4(), name="Distribuzione Nord S.r.l.", vat_number="IT01234567890")
ROSSI = Fornitore(id=uuid.uuid4(), name="Rossi & Figli S.p.A.", vat_number=None)
CISCO = Fornitore(id=uuid.uuid4(), name="Cisco", vat_number=None)
TUTTI = [NORD, ROSSI, CISCO]


def test_la_partita_iva_e_una_prova() -> None:
    """Undici cifre non capitano per caso: se ci sono, è lui — anche se il
    nome sulla carta intestata è scritto in un modo che non combacia."""
    testo = "DISTRIB. NORD\nP.IVA 01234567890\nDDT n. 5566 del 03/09/2026\n"

    assert riconosci(testo, TUTTI) == (NORD.id, "piva")


def test_il_nome_nella_testata() -> None:
    testo = "ROSSI E FIGLI SPA\nVia Example 1\nDOCUMENTO DI TRASPORTO n. 42\n"

    assert riconosci(testo, TUTTI) == (ROSSI.id, "intestazione")


def test_la_marca_delle_righe_non_e_il_fornitore() -> None:
    """Il falso positivo preso caricando una bolla vera sull'installazione.

    Il fornitore è «Tecno Forniture», che in anagrafica non c'è; nelle righe
    ci sono dieci switch Cisco, e Cisco in anagrafica c'è. Con la testata
    misurata a caratteri il nome finiva dentro la finestra e la bolla veniva
    assegnata a Cisco — con sicurezza, e sbagliando. La testata finisce dove
    comincia la bolla.
    """
    testo = (
        "TECNO FORNITURE SRL\nVia Example 9 - Roma\n"
        "D.D.T. n. 4141/2026 del 03/09/2026\n"
        "1  C9200L-24P-4G-E  Switch Cisco Catalyst 24p  2 PZ\n"
        "2  C9200L-48P-4G-E  Switch Cisco Catalyst 48p  1 PZ\n"
    )

    assert riconosci(testo, TUTTI) is None


def test_il_nome_in_mezzo_alle_righe_non_conta() -> None:
    """Il caso che rende inutile un riconoscimento ingenuo.

    Su una bolla di switch Cisco la parola «Cisco» è su ogni riga, ma il
    fornitore è il distributore che li ha venduti. Cercare il nome ovunque
    assegnerebbe la bolla al costruttore, con sicurezza e sbagliando.
    """
    testo = (
        "DISTRIBUZIONE NORD SRL\nVia Example 1 - P.IVA 01234567890\n"
        "DDT n. 77\n1  C9200L-24P-4G-E  Switch Cisco Catalyst  4 PZ\n"
        "2  C9200L-48P-4G-E  Switch Cisco Catalyst  2 PZ\n"
    )

    scelto = riconosci(testo, TUTTI)

    assert scelto is not None
    assert scelto[0] == NORD.id


def test_due_fornitori_nella_testata_non_si_indovinano() -> None:
    testo = "ROSSI E FIGLI SPA per conto di CISCO\nDDT n. 42\n"

    assert riconosci(testo, [ROSSI, CISCO]) is None


def test_senza_nessuna_corrispondenza_non_si_assegna_niente() -> None:
    assert riconosci("BOLLA DI CONSEGNA n. 1\nMerce varia\n", TUTTI) is None


def test_un_documento_illeggibile_non_ha_fornitore() -> None:
    assert riconosci("", TUTTI) is None
    assert riconosci("   ", TUTTI) is None


@pytest.mark.parametrize(
    "scritto_nel_documento",
    ["DISTRIBUZIONE NORD SRL", "Distribuzione Nord S.R.L.", "distribuzione nord"],
)
def test_la_forma_societaria_non_cambia_il_fornitore(scritto_nel_documento) -> None:
    testo = f"{scritto_nel_documento}\nDDT n. 9\n"

    scelto = riconosci(testo, TUTTI)

    assert scelto is not None
    assert scelto[0] == NORD.id
