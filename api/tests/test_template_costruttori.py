"""I template dei costruttori, provati contro il testo di un'etichetta.

Non si prova una regex per volta: si carica l'intero elenco dei template
attivi dell'installazione, come fa il riconoscimento automatico, e si guarda
**quale vince** e **cosa estrae**. È l'unica domanda che conta — una regex
giusta in un template che perde non serve a niente, e il modo in cui un
template nuovo fa danno è proprio rubando l'etichetta a un altro.

I seriali qui sono inventati ma della forma giusta: hanno la lunghezza e la
struttura di quelli veri senza esserlo (§7.5).
"""

import pytest

from app.services.extraction import pipeline
from app.services.extraction.templates import load_active_templates

# (etichetta, testo che l'OCR restituirebbe, template atteso, seriale atteso)
CASI = [
    (
        "Cisco",
        "cisco\nMODEL: C9200L-24P-4G-E\nS/N: ZZO0000TEST\nMAC: 00:11:22:33:44:55\n",
        "Cisco / etichetta dispositivo",
        "ZZO0000TEST",
    ),
    (
        "Meraki",
        "Cisco Meraki\nSERIAL: QZZZ-TEST-0001\nMODEL: MS120-8LP\n",
        "Meraki / etichetta scatola",
        "QZZZ-TEST-0001",
    ),
    (
        "Fortinet",
        "FORTINET\nModel: FG-60F\nS/N: FZZTEST000000000\n",
        "Fortinet / etichetta dispositivo",
        "FZZTEST000000000",
    ),
    (
        "Palo Alto",
        "PALO ALTO NETWORKS\nPA-440\nS/N: 001100110011\n",
        "Palo Alto / etichetta dispositivo",
        "001100110011",
    ),
    (
        "Dell",
        "DELL\nPowerSwitch N1548P\nSERVICE TAG: ZZTEST1\n",
        "Dell / etichetta dispositivo",
        "ZZTEST1",
    ),
    (
        "HPE Aruba",
        "Hewlett Packard Enterprise\nSKU: J9772A\nSERIAL NO: ZZTEST0001\n",
        "HPE Aruba / etichetta dispositivo",
        "ZZTEST0001",
    ),
    (
        "Juniper",
        "JUNIPER NETWORKS\nMODEL: EX2300-24T\nS/N: ZZTEST000001\n",
        "Juniper / etichetta dispositivo",
        "ZZTEST000001",
    ),
]


@pytest.fixture(autouse=True)
def _senza_codici_a_barre(monkeypatch):
    """Solo OCR: il codice a barre risolverebbe tutto da sé e non direbbe
    niente su quale template sa leggere l'etichetta stampata."""
    monkeypatch.setattr(pipeline, "decode_barcodes", lambda image_bytes: [])


@pytest.mark.parametrize("etichetta, testo, atteso, seriale", CASI)
async def test_l_etichetta_finisce_al_template_giusto(
    app_db_session, monkeypatch, etichetta, testo, atteso, seriale
) -> None:
    monkeypatch.setattr(pipeline, "run_ocr", lambda image_bytes, doc_type: testo)
    template = await load_active_templates(app_db_session)

    scelto = await pipeline.auto_detect_template(template, [b"finta-immagine"])

    assert scelto is not None, f"nessun template scelto per {etichetta}"
    assert scelto.name == atteso
    esito = await pipeline.run_extraction([b"finta-immagine"], scelto)
    assert esito.fields["serial_number"].value == seriale


async def test_una_bolla_non_finisce_a_un_template_di_etichetta(
    app_db_session, monkeypatch
) -> None:
    """Il rischio vero di un pacchetto di template: sono tutte etichette, e
    una bolla ha molti più codici in giro a cui aggrapparsi."""
    testo = (
        "SPETT.LE MAGAZZINO\nDOCUMENTO DI TRASPORTO\n"
        "D.D.T. N. 12345/2026 DEL 03/09/2026\n"
        "VS. ORDINE: ORD-2026-0099\n"
        "1  C9200L-24P-4G-E  Switch 24 porte  2 PZ\n"
    )
    monkeypatch.setattr(pipeline, "run_ocr", lambda image_bytes, doc_type: testo)
    template = await load_active_templates(app_db_session)

    scelto = await pipeline.auto_detect_template(template, [b"finta-immagine"])

    assert scelto is not None
    assert scelto.doc_type == "delivery_note"


async def test_le_parole_della_bolla_italiana(app_db_session, monkeypatch) -> None:
    """«D.D.T. n.» e «Vs. ordine» sono come si scrive su una bolla italiana:
    prima il template conosceva solo «DDT» e «ORDINE»."""
    testo = "D.D.T. N. 12345/2026 DEL 03/09/2026\nVS. ORDINE: ORD-2026-0099\n"
    monkeypatch.setattr(pipeline, "run_ocr", lambda image_bytes, doc_type: testo)
    template = await load_active_templates(app_db_session)
    bolla = next(t for t in template if t.doc_type == "delivery_note")

    esito = await pipeline.run_extraction([b"finta-immagine"], bolla)

    assert esito.fields["ddt_number"].value == "12345/2026"
    assert esito.fields["ddt_date"].value == "03/09/2026"


async def test_un_campo_pescato_a_caso_non_fa_vincere_un_template(
    app_db_session, monkeypatch
) -> None:
    """Il caso preso leggendo un'etichetta HPE vera, non a tavolino.

    L'OCR sbaglia una lettera del codice prodotto, quindi il template HPE
    risolve solo il seriale. Il template dell'alimentatore risolve il seriale
    (il suo pattern aggancia qualunque codice) e in più aggancia «HEWLETT»
    come codice prodotto, a confidenza bassa perché non c'era nessuna parola
    chiave vicino. Quel punto in più gli faceva vincere l'etichetta: un
    template guadagnava dall'essere impreciso.
    """
    testo = "Hewlett Packard Enterprise\nSKU: 39772A\nSERIAL NO: ZZTESTO001\n"
    monkeypatch.setattr(pipeline, "run_ocr", lambda image_bytes, doc_type: testo)
    template = await load_active_templates(app_db_session)

    scelto = await pipeline.auto_detect_template(template, [b"finta-immagine"])

    assert scelto is not None
    assert scelto.name == "HPE Aruba / etichetta dispositivo"


async def test_un_seriale_di_dodici_cifre_non_diventa_un_mac(
    app_db_session, monkeypatch
) -> None:
    """Un MAC senza separatori sono dodici cifre esadecimali, ed è anche la
    forma del seriale di un Palo Alto: lo stesso codice finiva in due campi."""
    testo = "PALO ALTO NETWORKS\nPA-440\nS/N: 001100110011\n"
    monkeypatch.setattr(pipeline, "run_ocr", lambda image_bytes, doc_type: testo)
    template = await load_active_templates(app_db_session)
    palo = next(t for t in template if t.name.startswith("Palo Alto"))

    esito = await pipeline.run_extraction([b"finta-immagine"], palo)

    assert esito.fields["serial_number"].value == "001100110011"
    assert "mac_address" not in esito.fields
