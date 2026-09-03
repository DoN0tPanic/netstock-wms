"""Template di lettura per i costruttori più diffusi, e la bolla italiana.

Perché in una migrazione e non a mano: un'installazione nuova deve poter
leggere le etichette senza che qualcuno ricostruisca a mano le regex, ed è la
stessa strada da cui sono arrivati i template iniziali (0002).

**Cosa c'è qui dentro e cosa no.** Ci sono i costruttori il cui seriale ha una
forma sua, riconoscibile: 16 caratteri che cominciano per F (Fortinet), 12
cifre (Palo Alto), il service tag da 7 (Dell). Non ci sono i costruttori il
cui seriale è «una stringa alfanumerica»: un template così non riconosce
niente, aggancia il primo codice che passa e — a parità di campi risolti —
può rubare l'etichetta a chi l'avrebbe letta bene. Meglio nessun template che
un template largo: senza, resta il ripiego generico e l'operatore corregge;
con, il dato sbagliato arriva già scritto nel campo e sembra giusto.

Tutti i template aggiunti sono etichette: condividono il profilo di lettura
`label`, quindi non aggiungono nemmeno un giro di OCR al riconoscimento
automatico (services/extraction/pipeline.py).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-03

"""
import json
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NUOVI_VENDOR = {
    "FORTINET": "Fortinet",
    "JUNIPER": "Juniper Networks",
    "DELL": "Dell Technologies",
}

# `keyword_window` è quanto lontano dalla parola chiave si accetta il valore:
# stretto dove la forma da sola non basterebbe (il service tag Dell sono sette
# caratteri qualsiasi, è «SERVICE TAG» a renderlo un service tag), più largo
# dove la forma è già una firma.
# Il separatore è obbligatorio. Senza, il pattern descrive «dodici cifre
# esadecimali di fila» e su un firewall Palo Alto agganciava il seriale — che
# è di dodici cifre — trascrivendolo come indirizzo MAC.
_MAC = {
    "name": "mac_address",
    "target": "unit.mac_address",
    "regex": r"^([0-9A-Fa-f]{2}[:\-.]){5}[0-9A-Fa-f]{2}$",
    "keywords": ["MAC", "MAC ADDRESS"],
    "required": False,
}

TEMPLATE = [
    {
        "name": "Fortinet / etichetta dispositivo",
        "vendor_code": "FORTINET",
        "category_code": None,
        "doc_type": "device_label",
        "priority": 20,
        "field_specs": {
            "fields": [
                {
                    "name": "serial_number",
                    "target": "unit.serial_number",
                    # Seriale Fortinet: sedici caratteri, il primo è una F.
                    "regex": r"^F[A-Z0-9]{15}$",
                    "keywords": ["S/N", "SN", "SERIAL"],
                    "keyword_window": 40,
                    "barcode_formats": ["Code128", "DataMatrix", "QRCode"],
                    "ocr_fixes": True,
                    "required": True,
                },
                {
                    "name": "part_number",
                    "target": "unit.catalog_item.part_number",
                    "regex": r"^F[A-Z0-9][A-Z0-9\-]{2,20}$",
                    "keywords": ["MODEL", "MODELLO", "P/N", "PID"],
                    "match_against_catalog": True,
                    "required": False,
                },
                _MAC,
            ],
            "llm_instructions": "Estrai i campi da un'etichetta di apparato Fortinet.",
        },
    },
    {
        "name": "Palo Alto / etichetta dispositivo",
        "vendor_code": "PALOALTO",
        "category_code": "FIREWALL",
        "doc_type": "device_label",
        "priority": 20,
        "field_specs": {
            "fields": [
                {
                    "name": "serial_number",
                    "target": "unit.serial_number",
                    # Tutto cifre: senza la parola chiave vicina aggancerebbe
                    # qualunque numero lungo stampato sull'etichetta, quindi la
                    # finestra resta stretta.
                    "regex": r"^[0-9]{12,15}$",
                    "keywords": ["S/N", "SN", "SERIAL"],
                    "keyword_window": 25,
                    "barcode_formats": ["Code128", "DataMatrix"],
                    "required": True,
                },
                {
                    "name": "part_number",
                    "target": "unit.catalog_item.part_number",
                    "regex": r"^PA[N]?-[A-Z0-9\-]{2,20}$",
                    "keywords": ["MODEL", "MODELLO", "P/N"],
                    "match_against_catalog": True,
                    "required": False,
                },
                _MAC,
            ],
            "llm_instructions": "Estrai i campi da un'etichetta di firewall Palo Alto Networks.",
        },
    },
    {
        "name": "Dell / etichetta dispositivo",
        "vendor_code": "DELL",
        "category_code": None,
        "doc_type": "device_label",
        "priority": 20,
        "field_specs": {
            "fields": [
                {
                    "name": "serial_number",
                    "target": "unit.serial_number",
                    # Sette caratteri qualsiasi non sono una firma: qui è la
                    # parola chiave a fare il lavoro, e la finestra è stretta
                    # apposta.
                    "regex": r"^[A-Z0-9]{7}$",
                    # Niente «ST» abbreviato fra le parole chiave: si cerca come
                    # sottostringa e finirebbe dentro «SYSTEM», aprendo una
                    # finestra su un'etichetta che non è Dell.
                    "keywords": ["SERVICE TAG", "SVC TAG", "SERVICE-TAG"],
                    "keyword_window": 18,
                    "barcode_formats": ["Code128", "Code39"],
                    "required": True,
                },
                {
                    "name": "part_number",
                    "target": "unit.catalog_item.part_number",
                    "regex": r"^[A-Z0-9][A-Z0-9\-]{4,24}$",
                    "keywords": ["MODEL", "MODELLO", "P/N", "PPID"],
                    "match_against_catalog": True,
                    "required": False,
                },
                _MAC,
            ],
            "llm_instructions": (
                "Estrai i campi da un'etichetta di apparato Dell. "
                "Il seriale è il Service Tag di sette caratteri."
            ),
        },
    },
    {
        "name": "HPE Aruba / etichetta dispositivo",
        "vendor_code": "HPE-ARUBA",
        "category_code": None,
        "doc_type": "device_label",
        "priority": 30,
        "field_specs": {
            "fields": [
                {
                    "name": "serial_number",
                    "target": "unit.serial_number",
                    # Dieci caratteri che cominciano con due lettere: una firma
                    # debole, per questo la priorità è più alta di Fortinet o
                    # Palo Alto — a parità di campi risolti vincono loro.
                    "regex": r"^[A-Z]{2}[A-Z0-9]{8}$",
                    "keywords": ["S/N", "SN", "SERIAL", "SERIAL NO"],
                    "keyword_window": 30,
                    "barcode_formats": ["Code128", "DataMatrix", "QRCode"],
                    "ocr_fixes": True,
                    "required": True,
                },
                {
                    "name": "part_number",
                    "target": "unit.catalog_item.part_number",
                    "regex": r"^[A-Z][0-9][A-Z0-9]{3,10}$",
                    "keywords": ["SKU", "P/N", "MODEL", "MODELLO"],
                    "match_against_catalog": True,
                    "required": False,
                },
                _MAC,
            ],
            "llm_instructions": "Estrai i campi da un'etichetta di apparato HPE o Aruba.",
        },
    },
    {
        "name": "Juniper / etichetta dispositivo",
        "vendor_code": "JUNIPER",
        "category_code": None,
        "doc_type": "device_label",
        "priority": 30,
        "field_specs": {
            "fields": [
                {
                    "name": "serial_number",
                    "target": "unit.serial_number",
                    "regex": r"^[A-Z]{2}[A-Z0-9]{10}$",
                    "keywords": ["S/N", "SN", "SERIAL"],
                    "keyword_window": 30,
                    "barcode_formats": ["Code128", "DataMatrix", "QRCode"],
                    "ocr_fixes": True,
                    "required": True,
                },
                {
                    "name": "part_number",
                    "target": "unit.catalog_item.part_number",
                    "regex": r"^(EX|QFX|MX|SRX|ACX|NFX|EX-|SRX-)[A-Z0-9\-]{2,20}$",
                    "keywords": ["MODEL", "MODELLO", "P/N"],
                    "match_against_catalog": True,
                    "required": False,
                },
                _MAC,
            ],
            "llm_instructions": "Estrai i campi da un'etichetta di apparato Juniper Networks.",
        },
    },
]


# Parole con cui una bolla italiana chiama le stesse cose. Non è un template
# nuovo: un secondo template di bolla farebbe solo concorrenza a quello che
# c'è, e a parità di campi risolti la scelta la deciderebbe la priorità invece
# del documento.
KEYWORD_BOLLA = {
    "ddt_number": [
        "DDT", "D.D.T.", "N.", "NR.", "NUMERO", "BOLLA",
        "DOCUMENTO DI TRASPORTO", "DOC. DI TRASPORTO",
    ],
    "ddt_date": ["DATA", "DEL", "DATA DOCUMENTO", "DATA EMISSIONE"],
    "po_number": [
        "ORDINE", "PO", "ODA", "VS. ORDINE", "VS ORDINE",
        "RIF. ORDINE", "N. ORDINE", "ORDINE N.",
    ],
    "supplier_name": [
        "MITTENTE", "FORNITORE", "RAGIONE SOCIALE", "SPETT.LE", "CEDENTE",
    ],
}


def _id_admin(conn) -> uuid.UUID:
    riga = conn.execute(
        sa.text("SELECT id FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1")
    ).first()
    if riga is None:
        raise RuntimeError("Nessun amministratore: il seed 0002 non è stato eseguito.")
    return riga[0]


def upgrade() -> None:
    conn = op.get_bind()
    admin_id = _id_admin(conn)

    for codice, nome in NUOVI_VENDOR.items():
        conn.execute(
            sa.text(
                """
                INSERT INTO vendors (code, name)
                SELECT :code, :name
                WHERE NOT EXISTS (SELECT 1 FROM vendors WHERE code = :code)
                """
            ),
            {"code": codice, "name": nome},
        )

    vendor_ids = dict(conn.execute(sa.text("SELECT code, id FROM vendors")).all())
    category_ids = dict(conn.execute(sa.text("SELECT code, id FROM categories")).all())

    for template in TEMPLATE:
        # Il nome è unico: se qualcuno l'ha già creato a mano, la sua versione
        # vince. Una migrazione non sovrascrive il lavoro di chi la usa.
        conn.execute(
            sa.text(
                """
                INSERT INTO extraction_templates
                    (id, name, vendor_id, category_id, doc_type, field_specs,
                     priority, created_by)
                SELECT :id, :name, :vendor_id, :category_id, :doc_type,
                       CAST(:field_specs AS JSONB), :priority, :created_by
                WHERE NOT EXISTS (
                    SELECT 1 FROM extraction_templates WHERE name = :name
                )
                """
            ),
            {
                "id": uuid.uuid4(),
                "name": template["name"],
                "vendor_id": vendor_ids.get(template["vendor_code"]),
                "category_id": category_ids.get(template["category_code"])
                if template["category_code"]
                else None,
                "doc_type": template["doc_type"],
                "field_specs": json.dumps(template["field_specs"]),
                "priority": template["priority"],
                "created_by": admin_id,
            },
        )

    # Le due modifiche a template esistenti valgono solo se nessuno li ha mai
    # toccati (`version = 1`): chi ha adattato un template al proprio magazzino
    # non se lo ritrova cambiato da un aggiornamento.
    riga = conn.execute(
        sa.text(
            "SELECT id, field_specs FROM extraction_templates "
            "WHERE name = 'Generico / bolla DDT' AND version = 1"
        )
    ).first()
    if riga is not None:
        specs = riga[1]
        for campo in specs.get("fields", []):
            aggiunte = KEYWORD_BOLLA.get(campo.get("name"))
            if not aggiunte:
                continue
            presenti = campo.get("keywords") or []
            campo["keywords"] = presenti + [k for k in aggiunte if k not in presenti]
        conn.execute(
            sa.text(
                "UPDATE extraction_templates SET field_specs = CAST(:specs AS JSONB), "
                "version = 2 WHERE id = :id"
            ),
            {"specs": json.dumps(specs), "id": riga[0]},
        )

    # L'etichetta alimentatore chiede `[A-Z0-9]{6,20}`, che aggancia qualunque
    # codice: è un ripiego, e la priorità deve dirlo. Con 50 stava davanti a
    # HPE e Juniper, che il seriale lo descrivono davvero.
    conn.execute(
        sa.text(
            "UPDATE extraction_templates SET priority = 90 "
            "WHERE name = 'Alimentatore / etichetta' AND version = 1 AND priority = 50"
        )
    )


def downgrade() -> None:
    """Toglie i template aggiunti e rimette la priorità dell'alimentatore.

    Le parole in più sulla bolla italiana restano: sono sinonimi di quello che
    il template già cercava, non fanno danno, e toglierle rischierebbe di
    portare via anche una parola aggiunta a mano nel frattempo.
    """
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM extraction_templates WHERE name = ANY(:nomi)"),
        {"nomi": [t["name"] for t in TEMPLATE]},
    )
    conn.execute(
        sa.text(
            "UPDATE extraction_templates SET priority = 50 "
            "WHERE name = 'Alimentatore / etichetta' AND priority = 90"
        )
    )
    conn.execute(
        sa.text("DELETE FROM vendors WHERE code = ANY(:codici)"),
        {"codici": list(NUOVI_VENDOR)},
    )
