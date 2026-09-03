"""Seed data: vendors, categories, locations, sample catalog, admin user,
extraction templates (§4.3).

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-26

"""
import json
import os
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _hash_password(plain: str) -> str:
    from argon2 import PasswordHasher

    return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4).hash(plain)


def upgrade() -> None:
    conn = op.get_bind()

    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_password:
        raise RuntimeError("ADMIN_PASSWORD non impostata: richiesta per il seed dell'admin.")

    admin_id = uuid.uuid4()
    conn.execute(
        sa.text(
            """
            INSERT INTO users (id, username, full_name, role, password_hash,
                                auth_provider, is_active, must_change_password)
            VALUES (:id, :username, 'Amministratore', 'admin', :password_hash,
                    'local', TRUE, TRUE)
            """
        ),
        {
            "id": admin_id,
            "username": admin_username,
            "password_hash": _hash_password(admin_password),
        },
    )

    vendors = {
        "CISCO": "Cisco Systems",
        "MERAKI": "Cisco Meraki",
        "PALOALTO": "Palo Alto Networks",
        "APC": "APC by Schneider Electric",
        "HPE-ARUBA": "HPE Aruba Networking",
        "GENERIC": "Generico / non specificato",
    }
    vendor_ids: dict[str, uuid.UUID] = {}
    for code, name in vendors.items():
        vendor_id = uuid.uuid4()
        vendor_ids[code] = vendor_id
        conn.execute(
            sa.text("INSERT INTO vendors (id, code, name) VALUES (:id, :code, :name)"),
            {"id": vendor_id, "code": code, "name": name},
        )

    categories = {
        "SWITCH": "Switch",
        "ROUTER": "Router",
        "AP": "Access Point",
        "FIREWALL": "Firewall",
        "PSU": "Alimentatori",
        "SFP": "Transceiver",
        "CABLE": "Cavi",
        "RACK": "Accessori rack",
        "ACCESSORY": "Accessori",
        "SPARE": "Ricambi",
    }
    category_ids: dict[str, uuid.UUID] = {}
    for code, name in categories.items():
        category_id = uuid.uuid4()
        category_ids[code] = category_id
        conn.execute(
            sa.text("INSERT INTO categories (id, code, name) VALUES (:id, :code, :name)"),
            {"id": category_id, "code": code, "name": name},
        )

    warehouse_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO locations (id, code, name, type) "
            "VALUES (:id, 'DEMO-WH', 'Magazzino dimostrativo', 'warehouse')"
        ),
        {"id": warehouse_id},
    )
    for n in range(1, 11):
        shelf_code = f"DEMO-WH-A{n:02d}"
        conn.execute(
            sa.text(
                "INSERT INTO locations (id, code, name, type, parent_id) "
                "VALUES (:id, :code, :name, 'shelf', :parent_id)"
            ),
            {
                "id": uuid.uuid4(),
                "code": shelf_code,
                "name": f"Scaffale A{n:02d}",
                "parent_id": warehouse_id,
            },
        )
    transit_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO locations (id, code, name, type) "
            "VALUES (:id, 'TRANSIT', 'Area transito', 'transit')"
        ),
        {"id": transit_id},
    )
    rma_id = uuid.uuid4()
    conn.execute(
        sa.text(
            "INSERT INTO locations (id, code, name, type) "
            "VALUES (:id, 'RMA', 'Area RMA', 'transit')"
        ),
        {"id": rma_id},
    )

    cisco_serial_pattern = r"^[A-Z]{3}[0-9]{4}[A-Z0-9]{4}$"
    meraki_serial_pattern = r"^Q[0-9A-Z]{3}-[0-9A-Z]{4}-[0-9A-Z]{4}$"

    catalog_items = [
        ("CISCO", "SWITCH", "C9200L-24P-4G-E", "Cisco Catalyst 9200L 24p PoE+", True,
         cisco_serial_pattern),
        ("CISCO", "SWITCH", "C9300-48P-A", "Cisco Catalyst 9300 48p PoE+", True,
         cisco_serial_pattern),
        ("MERAKI", "SWITCH", "MS120-8LP-HW", "Meraki MS120-8LP", True, meraki_serial_pattern),
        ("MERAKI", "AP", "MR46-HW", "Meraki MR46 Access Point", True, meraki_serial_pattern),
        ("MERAKI", "FIREWALL", "MX68-HW", "Meraki MX68 Security Appliance", True,
         meraki_serial_pattern),
        ("CISCO", "SFP", "GLC-LH-SMD", "Cisco SFP 1G LX/LH", True, None),
        ("CISCO", "SFP", "SFP-10G-SR", "Cisco SFP+ 10G SR", True, None),
        ("CISCO", "PSU", "PWR-C1-350WAC", "Alimentatore Cisco 350W AC", True, None),
        ("CISCO", "PSU", "PWR-C5-125WAC", "Alimentatore Cisco 125W AC", True, None),
        ("CISCO", "CABLE", "CAB-TA-EU", "Cavo alimentazione EU", False, None),
    ]
    for vendor_code, category_code, part_number, name, is_serialized, pattern in catalog_items:
        conn.execute(
            sa.text(
                """
                INSERT INTO catalog_items
                    (id, vendor_id, category_id, part_number, name, is_serialized,
                     uom, serial_pattern)
                VALUES (:id, :vendor_id, :category_id, :part_number, :name,
                        :is_serialized, 'PZ', :pattern)
                """
            ),
            {
                "id": uuid.uuid4(),
                "vendor_id": vendor_ids[vendor_code],
                "category_id": category_ids[category_code],
                "part_number": part_number,
                "name": name,
                "is_serialized": is_serialized,
                "pattern": pattern,
            },
        )

    conn.execute(
        sa.text(
            """
            INSERT INTO catalog_items
                (id, vendor_id, category_id, part_number, name, is_serialized, uom)
            VALUES (:id, :vendor_id, :category_id, 'PATCH-CAT6-1M', 'Patch cord Cat6 1m',
                    FALSE, 'PZ')
            """
        ),
        {
            "id": uuid.uuid4(),
            "vendor_id": vendor_ids["GENERIC"],
            "category_id": category_ids["CABLE"],
        },
    )

    templates = [
        {
            "name": "Cisco / etichetta dispositivo",
            "vendor_code": "CISCO",
            "category_code": None,
            "doc_type": "device_label",
            "priority": 10,
            "field_specs": {
                "fields": [
                    {
                        "name": "serial_number",
                        "target": "unit.serial_number",
                        "regex": cisco_serial_pattern,
                        "keywords": ["S/N", "SN", "SERIAL", "SERIE"],
                        "keyword_window": 40,
                        "barcode_formats": ["Code128", "DataMatrix", "QRCode", "MicroQRCode"],
                        "ocr_fixes": True,
                        "required": True,
                    },
                    {
                        "name": "part_number",
                        "target": "unit.catalog_item.part_number",
                        "regex": r"^[A-Z0-9][A-Z0-9\-]{4,24}$",
                        "keywords": ["PID", "MODEL", "MODELLO", "P/N"],
                        "match_against_catalog": True,
                        "required": True,
                    },
                    {
                        "name": "mac_address",
                        "target": "unit.mac_address",
                        "regex": r"^([0-9A-Fa-f]{2}[:\-.]?){5}[0-9A-Fa-f]{2}$",
                        "keywords": ["MAC", "MAC ADDRESS"],
                        "required": False,
                    },
                ],
                "llm_instructions": (
                    "Estrai i campi da un'etichetta di apparato di rete Cisco. "
                    "Rispondi solo con JSON."
                ),
            },
        },
        {
            "name": "Meraki / etichetta scatola",
            "vendor_code": "MERAKI",
            "category_code": None,
            "doc_type": "box_label",
            "priority": 10,
            "field_specs": {
                "fields": [
                    {
                        "name": "serial_number",
                        "target": "unit.serial_number",
                        "regex": meraki_serial_pattern,
                        "keywords": ["S/N", "SERIAL"],
                        "keyword_window": 40,
                        "barcode_formats": ["QRCode", "MicroQRCode"],
                        "required": True,
                    },
                    {
                        "name": "part_number",
                        "target": "unit.catalog_item.part_number",
                        "regex": r"^[A-Z0-9][A-Z0-9\-]{4,24}$",
                        "keywords": ["MODEL", "PID"],
                        "match_against_catalog": True,
                        "required": False,
                    },
                    {
                        "name": "mac_address",
                        "target": "unit.mac_address",
                        "regex": r"^([0-9A-Fa-f]{2}[:\-.]?){5}[0-9A-Fa-f]{2}$",
                        "keywords": ["MAC"],
                        "required": False,
                    },
                ],
                "llm_instructions": "Estrai i campi da un'etichetta di scatola Meraki.",
            },
        },
        {
            "name": "Alimentatore / etichetta",
            "vendor_code": None,
            "category_code": "PSU",
            "doc_type": "device_label",
            "priority": 50,
            "field_specs": {
                "fields": [
                    {
                        "name": "serial_number",
                        "target": "unit.serial_number",
                        "regex": r"^[A-Z0-9]{6,20}$",
                        "keywords": ["S/N", "SN", "SERIAL"],
                        "keyword_window": 30,
                        "required": True,
                    },
                    {
                        "name": "part_number",
                        "target": "unit.catalog_item.part_number",
                        "regex": r"^[A-Z0-9][A-Z0-9\-]{4,24}$",
                        "keywords": ["P/N", "MODEL"],
                        "match_against_catalog": True,
                        "required": False,
                    },
                ],
                "llm_instructions": "Estrai i campi da un'etichetta di alimentatore.",
            },
        },
        {
            "name": "Generico / bolla DDT",
            "vendor_code": None,
            "category_code": None,
            "doc_type": "delivery_note",
            "priority": 100,
            "field_specs": {
                "fields": [
                    {
                        "name": "ddt_number",
                        "target": "delivery_note.number",
                        "regex": r"[0-9]{1,10}(/[0-9]{2,4})?",
                        # "BOLLA" deliberately excluded: it typically appears in the
                        # document title ("BOLLA DI CONSEGNA"), far from the actual
                        # number, and the keyword-window search stops there before
                        # ever reaching it — "DDT"/"N." sit right next to the value.
                        "keywords": ["DDT", "N."],
                        "keyword_window": 40,
                        "required": True,
                    },
                    {
                        "name": "ddt_date",
                        "target": "delivery_note.note_date",
                        "regex": r"[0-3]?[0-9][/\-][0-1]?[0-9][/\-][0-9]{2,4}",
                        "keywords": ["DATA"],
                        "keyword_window": 20,
                        "required": True,
                    },
                    {
                        "name": "po_number",
                        "target": "delivery_note.po_number",
                        "regex": r"[A-Z0-9\-]{4,20}",
                        "keywords": ["ORDINE", "PO", "ODA"],
                        "keyword_window": 30,
                        "required": False,
                    },
                    {
                        "name": "supplier_name",
                        "target": "delivery_note.supplier_name",
                        "regex": r"[A-Za-z ]{3,40}",
                        "keywords": ["MITTENTE", "FORNITORE"],
                        "keyword_window": 40,
                        "required": False,
                    },
                ],
                "llm_instructions": "Estrai i campi principali da una bolla di consegna (DDT).",
            },
        },
    ]

    for template in templates:
        conn.execute(
            sa.text(
                """
                INSERT INTO extraction_templates
                    (id, name, vendor_id, category_id, doc_type, field_specs,
                     priority, created_by)
                VALUES (:id, :name, :vendor_id, :category_id, :doc_type,
                        CAST(:field_specs AS JSONB), :priority, :created_by)
                """
            ),
            {
                "id": uuid.uuid4(),
                "name": template["name"],
                "vendor_id": vendor_ids.get(template["vendor_code"])
                if template["vendor_code"]
                else None,
                "category_id": category_ids.get(template["category_code"])
                if template["category_code"]
                else None,
                "doc_type": template["doc_type"],
                "field_specs": json.dumps(template["field_specs"]),
                "priority": template["priority"],
                "created_by": admin_id,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM extraction_templates"))
    conn.execute(sa.text("DELETE FROM catalog_items"))
    conn.execute(sa.text("DELETE FROM locations"))
    conn.execute(sa.text("DELETE FROM categories"))
    conn.execute(sa.text("DELETE FROM vendors"))
    conn.execute(sa.text("DELETE FROM users"))
