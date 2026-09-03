"""Test della lettura strutturale della bolla.

Il modello non viene interrogato: si sostituisce la sua risposta, perché quello
che va garantito qui non è la bravura del modello — che cambia con la versione
e con l'hardware — ma il fatto che **qualunque cosa risponda**, ciò che esce non
contiene valori che nel documento non ci sono.
"""

import uuid
from decimal import Decimal

import pytest

from app.services.extraction import document_ai
from app.services.extraction.document_ai import (
    _condense_for_model,
    _match_catalog,
    _scan_serials,
    _to_decimal,
    propose_document_lines,
)
from app.services.extraction.document_lines import CatalogItemRef

# Ricostruzione della forma di una bolla di distributore, con tutte le
# caratteristiche che rendono il caso difficile: intestazione bilingue, colonne
# "ordinato" e "consegnato" che non coincidono, seriali in linea separati da
# virgola, una riga con il seriale secondario fra parentesi, rumore che somiglia
# a un codice (EAN, riferimenti d'ordine) e una riga che non è merce.
#
# I valori sono inventati di proposito: un documento reale non entra nel
# repository (§7.5 — le immagini non toccano mai un volume persistente, e i
# dati di un cliente vero non stanno in un file di test).
OCR_TEXT = """Pos. Bestellt Geliefert Artikel-Nr. Artikelbeschreibung / Hersteller Nr.
1 24 4 A12BC34 CAVO STACK 1M TIPO 4
SW-STACK-1M=
EU#- 000000000 CLIENTE ESEMPIO SPA
SN: ZZQ4471AK10, SN: ZZQ4471AK11, SN: ZZQ4472BM20, SN: ZZQ4472BM21
EAN/UPC 123456789012
5 24 24 A12BD90 SWITCH 24 PORTE POE+ STACK
SW-STACK-KIT=
SN: ZZR4473CN30 (SN2: ZZR4473CN31)
SN: ZZR4474DP40 (SN2: ZZR4474DP41)
6 1 1 SPESE DI TRASPORTO
"""


def _item(part_number: str, *, serialized: bool = True) -> CatalogItemRef:
    return CatalogItemRef(
        id=uuid.uuid4(),
        part_number=part_number,
        name=part_number,
        vendor_code="CSC",
        is_serialized=serialized,
        serial_pattern=None,
    )


class TestSerialScanner:
    def test_finds_every_labelled_serial(self):
        found = [hit.value for hit in _scan_serials(OCR_TEXT)]
        assert found == [
            "ZZQ4471AK10",
            "ZZQ4471AK11",
            "ZZQ4472BM20",
            "ZZQ4472BM21",
            "ZZR4473CN30",
            "ZZR4474DP40",
        ]

    def test_secondary_serial_is_kept_apart(self):
        """SN2 è un secondo codice dello stesso pezzo, non un altro pezzo.

        Contarlo come pezzo raddoppierebbe la giacenza di quella riga.
        """
        hits = {hit.value: hit.secondary for hit in _scan_serials(OCR_TEXT)}
        assert hits["ZZR4473CN30"] == "ZZR4473CN31"
        assert hits["ZZQ4471AK10"] is None

    def test_ignores_numbers_that_are_not_serials(self):
        found = [hit.value for hit in _scan_serials(OCR_TEXT)]
        assert "123456789012" not in found  # EAN/UPC
        assert "000000000" not in found  # riferimento d'ordine

    def test_every_value_is_a_literal_substring(self):
        for hit in _scan_serials(OCR_TEXT):
            assert hit.value in OCR_TEXT.upper()


class TestCondense:
    def test_drops_serial_lines_and_boilerplate(self):
        condensed = _condense_for_model(OCR_TEXT)
        assert "SN: ZZQ4471AK10" not in condensed
        assert "EAN/UPC" not in condensed
        assert "EU#-" not in condensed

    def test_keeps_the_table_rows(self):
        condensed = _condense_for_model(OCR_TEXT)
        assert "A12BC34" in condensed
        assert "SW-STACK-1M=" in condensed
        assert "SPESE DI TRASPORTO" in condensed

    def test_never_returns_empty(self):
        """Se il filtro togliesse tutto, meglio il testo grezzo che niente."""
        assert _condense_for_model("SN: ABC123456\nSN: ABC123457").strip()


class TestCatalogMatch:
    def test_trailing_equals_is_ignored(self):
        """Sulle bolle i codici Cisco finiscono con "=", a catalogo no."""
        item = _item("SW-STACK-KIT")
        assert _match_catalog("SW-STACK-KIT=", [item]) is item

    def test_does_not_pick_a_merely_closest_row(self):
        assert _match_catalog("SW-NM-4X", [_item("WS-C2960X-24")]) is None

    def test_short_codes_are_not_matched(self):
        assert _match_catalog("AB", [_item("AB")]) is None


class TestQuantities:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("4", Decimal(4)), ("1,5", Decimal("1.5")), ("0", None), ("", None), ("abc", None)],
    )
    def test_parsing(self, raw, expected):
        assert _to_decimal(raw) == expected


@pytest.mark.asyncio
class TestProposal:
    async def _propose(self, monkeypatch, model_reply, catalog=None):
        async def fake_call(_text):
            return model_reply

        monkeypatch.setattr(document_ai, "_call_model", fake_call)
        return await propose_document_lines(OCR_TEXT, catalog or [])

    async def test_uses_delivered_quantity_not_ordered(self, monkeypatch):
        proposal = await self._propose(
            monkeypatch,
            {"lines": [{"position": "1", "item_no": "A12BC34", "vpn": "SW-STACK-1M=",
                        "description": "STACKING CABLE", "qty_ordered": "24",
                        "qty_delivered": "4", "is_goods": True}]},
        )
        line = proposal.lines[0]
        assert line.quantity == Decimal(4)
        assert line.quantity_ordered == Decimal(24)
        assert any("Ordinati 24, consegnati 4" in warning for warning in line.warnings)

    async def test_serials_come_from_the_document_not_the_model(self, monkeypatch):
        """Il modello non elenca seriali: vengono ritagliati dal testo OCR.

        Anche se ne proponesse (una versione futura, un prompt modificato),
        quelli finiscono ignorati.
        """
        proposal = await self._propose(
            monkeypatch,
            {"lines": [{"position": "1", "item_no": "A12BC34", "vpn": "SW-STACK-1M=",
                        "description": "STACKING CABLE", "qty_ordered": "24",
                        "qty_delivered": "4", "is_goods": True,
                        "serials": ["INVENTATO123", "ANCHEQUESTO456"]}]},
        )
        serials = proposal.lines[0].serials
        assert "INVENTATO123" not in serials
        assert "ANCHEQUESTO456" not in serials
        assert "ZZQ4471AK10" in serials
        # Con una sola riga proposta il blocco arriva a fine documento, quindi
        # raccoglie tutti i seriali: il raggruppamento fine lo dà il confine con
        # la riga successiva (vedi test_serials_are_split_between_lines_by_position).
        assert all(value in OCR_TEXT.upper() for value in serials)

    async def test_serials_are_split_between_lines_by_position(self, monkeypatch):
        proposal = await self._propose(
            monkeypatch,
            {"lines": [
                {"position": "1", "item_no": "A12BC34", "vpn": "SW-STACK-1M=",
                 "description": "CABLE", "qty_ordered": "24", "qty_delivered": "4",
                 "is_goods": True},
                {"position": "5", "item_no": "A12BD90", "vpn": "SW-STACK-KIT=",
                 "description": "STACK MODULE", "qty_ordered": "24",
                 "qty_delivered": "24", "is_goods": True},
            ]},
        )
        first, second = proposal.lines
        assert first.serials == [
            "ZZQ4471AK10", "ZZQ4471AK11", "ZZQ4472BM20", "ZZQ4472BM21",
        ]
        assert second.serials == ["ZZR4473CN30", "ZZR4474DP40"]
        assert second.secondary_serials == ["ZZR4473CN31", "ZZR4474DP41"]

    async def test_fabricated_lines_are_discarded(self, monkeypatch):
        """Il caso osservato dal vero: su una pagina illeggibile il modello
        smetteva di analizzare e ricopiava l'esempio contenuto nel prompt,
        producendo righe che nel documento non compaiono."""
        proposal = await self._propose(
            monkeypatch,
            {"lines": [{"position": "7", "item_no": "881AB42", "vpn": "WS-C2960X-24=",
                        "description": "24-PORT GIGABIT SWITCH", "qty_ordered": "10",
                        "qty_delivered": "6", "is_goods": True}]},
        )
        assert proposal.lines == []

    async def test_non_goods_lines_never_become_stock(self, monkeypatch):
        proposal = await self._propose(
            monkeypatch,
            {"lines": [{"position": "6", "item_no": "", "vpn": "",
                        "description": "SPESE DI TRASPORTO", "qty_ordered": "1",
                        "qty_delivered": "1", "is_goods": False}]},
        )
        assert proposal.lines == []
        assert proposal.non_goods == ["SPESE DI TRASPORTO"]

    async def test_unknown_model_is_reported_as_unmatched_not_invented(self, monkeypatch):
        """Un modello che non è a catalogo non viene inventato: la riga arriva
        con `catalog_item` vuoto e il codice letto dal documento.

        Il fatto **non** viene messo fra gli avvisi: quelli descrivono la
        lettura del documento, mentre "manca a catalogo" descrive lo stato del
        catalogo adesso, e da lì non si aggiornerebbe più quando l'operatore
        crea l'articolo. Lo deriva chi disegna, da questo campo.
        """
        proposal = await self._propose(
            monkeypatch,
            {"lines": [{"position": "1", "item_no": "A12BC34", "vpn": "SW-STACK-1M=",
                        "description": "CABLE", "qty_ordered": "24",
                        "qty_delivered": "4", "is_goods": True}]},
        )
        line = proposal.lines[0]
        assert line.catalog_item is None
        assert line.part_number == "SW-STACK-1M="
        assert not any("catalogo" in warning for warning in line.warnings)

    async def test_known_model_is_resolved(self, monkeypatch):
        item = _item("SW-STACK-1M")
        proposal = await self._propose(
            monkeypatch,
            {"lines": [{"position": "1", "item_no": "A12BC34", "vpn": "SW-STACK-1M=",
                        "description": "CABLE", "qty_ordered": "24",
                        "qty_delivered": "4", "is_goods": True}]},
            catalog=[item],
        )
        assert proposal.lines[0].catalog_item is item

    async def test_serial_count_mismatch_is_reported(self, monkeypatch):
        proposal = await self._propose(
            monkeypatch,
            {"lines": [{"position": "1", "item_no": "A12BC34", "vpn": "SW-STACK-1M=",
                        "description": "CABLE", "qty_ordered": "24",
                        "qty_delivered": "2", "is_goods": True}]},
        )
        assert any(
            "seriali ma la quantità consegnata" in warning
            for warning in proposal.lines[0].warnings
        )

    async def test_a_model_failure_is_not_an_error(self, monkeypatch):
        """Se il modello non risponde l'operatore resta col risultato
        deterministico: la ricezione non deve rompersi per questo."""

        async def broken(_text):
            raise ValueError("ollama irraggiungibile")

        monkeypatch.setattr(document_ai, "_call_model", broken)
        proposal = await propose_document_lines(OCR_TEXT, [])
        assert proposal.lines == []

    async def test_two_lines_anchored_at_the_same_spot_do_not_break_the_reading(
        self, monkeypatch
    ):
        """Regressione: le righe venivano ordinate come coppie (posizione, dati).

        Con due righe ancorate allo stesso punto — il modello che ripete lo
        stesso codice, cosa che capita su una pagina difficile — Python passava
        a confrontare i due dizionari e sollevava `TypeError`. L'intera analisi
        moriva: nessuna proposta, nessun errore visibile, solo un'attesa che non
        finiva mai.
        """
        riga = {"position": "1", "item_no": "A12BC34", "vpn": "SW-STACK-1M=",
                "description": "CABLE", "qty_ordered": "24", "qty_delivered": "4",
                "is_goods": True}
        proposal = await self._propose(monkeypatch, {"lines": [riga, dict(riga)]})
        # La ripetizione cade: nel testo il codice compare una volta sola, e
        # tenerla avrebbe prodotto una riga fantasma senza seriali accanto a
        # quella buona — che poi impedisce di confermare la ricezione, perché
        # un articolo serializzato senza seriali non si può ricevere.
        assert len(proposal.lines) == 1
        assert proposal.lines[0].serials

    async def test_the_same_article_listed_twice_keeps_both_lines(self, monkeypatch):
        """Un documento può elencare davvero lo stesso articolo due volte: lì
        la seconda occorrenza del codice esiste, e la riga va tenuta."""
        testo = (
            "1 4 4 A12BC34 CABLE\nSW-STACK-1M=\nSN: ZZQ4471AK10\n"
            "9 2 2 A12BC34 CABLE\nSW-STACK-1M=\nSN: ZZQ4472BM20\n"
        )

        async def fake_call(_text):
            return {"lines": [
                {"position": "1", "item_no": "A12BC34", "vpn": "SW-STACK-1M=",
                 "description": "CABLE", "qty_ordered": "4", "qty_delivered": "4",
                 "is_goods": True},
                {"position": "9", "item_no": "A12BC34", "vpn": "SW-STACK-1M=",
                 "description": "CABLE", "qty_ordered": "2", "qty_delivered": "2",
                 "is_goods": True},
            ]}

        monkeypatch.setattr(document_ai, "_call_model", fake_call)
        proposal = await propose_document_lines(testo, [])
        assert [line.serials for line in proposal.lines] == [["ZZQ4471AK10"], ["ZZQ4472BM20"]]
