"""Registry mapping an extraction field name to the frontend form target.

Adding a new field to a template requires adding its target here once —
never a code change per vendor (§7.3).
"""

EXTRACTION_TARGETS: dict[str, str] = {
    "serial_number": "unit.serial_number",
    "part_number": "unit.catalog_item.part_number",
    "mac_address": "unit.mac_address",
    "ddt_number": "delivery_note.number",
    "ddt_date": "delivery_note.note_date",
    "po_number": "delivery_note.po_number",
    "supplier_name": "delivery_note.supplier_name",
}
