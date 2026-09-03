export type UUID = string;
export type ISODate = string;
export type ISODateTime = string;
export type Decimal = number;
export type UserRole = 'viewer' | 'operator' | 'admin';
export type LocationType = 'warehouse' | 'shelf' | 'box' | 'remote_site' | 'transit';
export type ItemCondition = 'new' | 'refurbished' | 'used' | 'faulty';
export type UnitStatus = 'in_stock' | 'reserved' | 'issued' | 'in_rma' | 'scrapped' | 'lost';
export type MovementType = 'receipt' | 'issue' | 'transfer' | 'return' | 'rma_out' | 'rma_in' | 'adjustment' | 'scrap';
export type ReservationStatus = 'open' | 'fulfilled' | 'cancelled' | 'expired';
export type TemplateDocType = 'device_label' | 'box_label' | 'delivery_note' | 'packing_list';
export type Confidence = 'high' | 'medium' | 'low';
export interface Timestamps { created_at: ISODateTime; updated_at: ISODateTime }
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }
export interface ApiErrorBody { error: { code: string; message: string; details: Record<string, unknown> } }
export interface User extends Timestamps { id: UUID; username: string; email: string | null; full_name: string; role: UserRole; auth_provider: string; is_active: boolean; must_change_password: boolean; last_login_at: ISODateTime | null; deleted_at: ISODateTime | null; can_purge: boolean }
// `removed` è falso per la chiusura dell'account e vero solo per la rimozione
// definitiva dal database; `traces` dice in quali tabelle e quante righe porta
// la sua firma, e `purgeable` se la rimozione definitiva è ancora possibile.
export interface UserDeleteResult { removed: boolean; username: string; traces: Record<string, number>; purgeable: boolean }
export interface AuthMe { id: UUID; username: string; email: string | null; full_name: string; role: UserRole; must_change_password: boolean; permissions: { can_write: boolean; can_administer: boolean } }
export interface LoginRequest { username: string; password: string }
export interface ChangePasswordRequest { current_password: string; new_password: string }
export interface Vendor extends Timestamps { id: UUID; code: string; name: string; notes: string | null; is_active: boolean }
export type VendorWrite = Pick<Vendor, 'code' | 'name'> & Partial<Pick<Vendor, 'notes' | 'is_active'>>;
export interface Category extends Timestamps { id: UUID; code: string; name: string; parent_id: UUID | null }
export type CategoryWrite = Pick<Category, 'code' | 'name'> & Partial<Pick<Category, 'parent_id'>>;
export interface Supplier extends Timestamps { id: UUID; name: string; vat_number: string | null; contact_ref: string | null; notes: string | null; is_active: boolean }
export type SupplierWrite = Pick<Supplier, 'name'> & Partial<Pick<Supplier, 'vat_number' | 'contact_ref' | 'notes' | 'is_active'>>;
export interface Location extends Timestamps { id: UUID; code: string; name: string; type: LocationType; parent_id: UUID | null; address: string | null; is_active: boolean }
// `code` è facoltativo: se manca lo ricava il server dal nome.
export type LocationWrite = Pick<Location, 'name' | 'type'> & Partial<Pick<Location, 'code' | 'parent_id' | 'address' | 'is_active'>>;
export interface CatalogItem extends Timestamps { id: UUID; vendor_id: UUID; category_id: UUID; part_number: string; name: string; description: string | null; is_serialized: boolean; uom: string; reorder_point: number | null; eol_date: ISODate | null; eos_date: ISODate | null; serial_pattern: string | null; notes: string | null; is_active: boolean }
export type CatalogItemWrite = Pick<CatalogItem, 'vendor_id' | 'category_id' | 'part_number' | 'name' | 'is_serialized'> & Partial<Pick<CatalogItem, 'description' | 'uom' | 'reorder_point' | 'eol_date' | 'eos_date' | 'serial_pattern' | 'notes' | 'is_active'>>;
export interface DeliveryNoteLine { id: UUID; delivery_note_id: UUID; line_number: number; catalog_item_id: UUID; qty_expected: Decimal; qty_received: Decimal; condition: ItemCondition; notes: string | null }
export interface DeliveryNote extends Timestamps { id: UUID; number: string; note_date: ISODate; supplier_id: UUID; po_number: string | null; carrier: string | null; tracking_number: string | null; received_at: ISODateTime; received_by: UUID; is_closed: boolean; notes: string | null; lines?: DeliveryNoteLine[]; movements?: StockMovement[]; units?: StockUnit[] }
export interface DeliveryNoteCreate { number: string; note_date: ISODate; supplier_id: UUID; po_number?: string | null; carrier?: string | null; tracking_number?: string | null; notes?: string | null; lines: Array<{ catalog_item_id: UUID; qty_expected: Decimal; condition: ItemCondition; notes?: string | null }> }
export interface ReceiveRequest { occurred_at?: ISODateTime; location_id: UUID; lines: Array<{ line_id: UUID; condition: ItemCondition; serials?: Array<{ serial_number: string; mac_address?: string; location_id?: UUID }>; quantity?: Decimal }>; confirm_warnings: string[] }
export interface ReceiveResponse { created_unit_ids: UUID[]; movement_ids: UUID[]; delivery_note_closed: boolean }
// Receiving stock that has no delivery note at all (found equipment, gear
// handed over without paperwork). The note can be linked afterwards on each
// resulting unit via unitsApi.attachDeliveryNote — see `POST /movements/receive`.
export interface FreeReceiveRequest { occurred_at?: ISODateTime; location_id: UUID; lines: Array<{ catalog_item_id: UUID; condition: ItemCondition; serials?: Array<{ serial_number: string; mac_address?: string; location_id?: UUID }>; quantity?: Decimal }>; confirm_warnings: string[] }
export interface FreeReceiveResponse { created_unit_ids: UUID[]; movement_ids: UUID[] }
export interface StockUnit extends Timestamps { id: UUID; catalog_item_id: UUID; serial_number: string; mac_address: string | null; status: UnitStatus; condition: ItemCondition; location_id: UUID | null; delivery_note_line_id: UUID | null; purchase_date: ISODate | null; warranty_end: ISODate | null; contract_ref: string | null; notes: string | null; catalog_item?: CatalogItem; movements?: StockMovement[]; part_number?: string | null; catalog_item_name?: string | null; vendor_code?: string | null; delivery_note_number?: string | null; location_code?: string | null }
export interface StockMovement { id: UUID; occurred_at: ISODateTime; type: MovementType; catalog_item_id: UUID; stock_unit_id: UUID | null; quantity: Decimal; condition: ItemCondition; location_from_id: UUID | null; location_to_id: UUID | null; delivery_note_id: UUID | null; reference: string | null; assignee: string | null; reason: string | null; reverses_id: UUID | null; performed_by: UUID; notes: string | null; created_at: ISODateTime; part_number?: string | null; serial_number?: string | null; location_from_code?: string | null; location_to_code?: string | null; performed_by_username?: string | null; is_reversed?: boolean }
export interface StockAvailability { catalog_item_id: UUID; part_number: string; name: string; vendor_code: string; category_code: string; is_serialized: boolean; reorder_point: number | null; qty_on_hand: Decimal; qty_reserved: Decimal; qty_available: Decimal; below_reorder_point: boolean; locations?: Array<{ location_id: UUID; location_code: string; quantity: Decimal }> }
export interface MovementItem { unit_id?: UUID; catalog_item_id?: UUID; quantity?: Decimal; condition?: ItemCondition }
export interface IssueRequest { occurred_at?: ISODateTime; location_from_id: UUID; reference: string; assignee?: string; items: MovementItem[]; reservation_id?: UUID; notes?: string }
export interface BulkItemRequest { catalog_item_id: UUID; quantity: Decimal; condition: ItemCondition }
// `/movements/transfer` and `/movements/return` take `unit_ids` + `bulk_items`
// (never a generic `items` array) — verified against the real Pydantic
// schemas in api/app/schemas/stock.py. A previous generic `MovementRequest`
// type papered over this and silently sent empty transfers (backend
// defaulted the missing fields to `[]` and returned 201 with no movements
// created). Keep each request shaped exactly like its endpoint.
export interface TransferRequest { occurred_at?: ISODateTime; location_from_id: UUID | null; location_to_id: UUID; unit_ids?: UUID[]; bulk_items?: BulkItemRequest[]; notes?: string }
export interface ReturnRequest { occurred_at?: ISODateTime; location_to_id: UUID; reference: string; unit_ids?: UUID[]; bulk_items?: BulkItemRequest[]; notes?: string }
export interface RmaMoveRequest { occurred_at?: ISODateTime; location_from_id: UUID; location_to_id: UUID; reference: string; unit_ids: UUID[]; notes?: string }
export interface AdjustRequest { occurred_at?: ISODateTime; reason: string; unit_id?: UUID; catalog_item_id?: UUID; quantity?: Decimal; condition?: ItemCondition; location_from_id?: UUID; location_to_id?: UUID; allow_negative?: boolean; notes?: string }
export interface ScrapRequest { occurred_at?: ISODateTime; reason: string; location_from_id: UUID; unit_id?: UUID; catalog_item_id?: UUID; quantity?: Decimal; condition?: ItemCondition; notes?: string }
export interface FieldSpec { name: string; target: string; regex: string; keywords: string[]; keyword_window?: number; barcode_formats?: string[]; ocr_fixes?: boolean; required: boolean; match_against_catalog?: boolean }
export interface ExtractionTemplate extends Timestamps { id: UUID; name: string; vendor_id: UUID | null; category_id: UUID | null; doc_type: TemplateDocType; field_specs: { fields: FieldSpec[]; llm_instructions?: string }; llm_prompt: string | null; priority: number; is_active: boolean; version: number; created_by: UUID }
export type ExtractionTemplateWrite = Pick<ExtractionTemplate, 'name' | 'doc_type' | 'field_specs'> & Partial<Pick<ExtractionTemplate, 'vendor_id' | 'category_id' | 'llm_prompt' | 'priority' | 'is_active'>>;
export interface ExtractedField { field: string; value: string; confidence: Confidence; source: string; corrected: boolean }
export interface ExtractionResult { run_id: string | null; template_id: string | null; template_name: string | null; engine: string; fields: Record<string, ExtractedField>; conflicts: Record<string, ExtractedField[]>; raw_barcodes: string[]; raw_ocr_text: string; duration_ms: number; matched_catalog_item?: Pick<CatalogItem, 'id' | 'part_number' | 'name'> & { vendor_code: string } | null }
export interface DeliveryNoteExtractionResult {
  // Identifica la lettura in `extraction_runs`: serve a poter dire, dopo, se
  // questa proposta è stata usata. È l'unico numero che permette di decidere
  // se questa parte del sistema vale quello che costa.
  run_id: string | null;
  fields: Record<string, ExtractedField>;
  // `quantity` è null quando il documento non dichiara una quantità riconoscibile:
  // meglio un campo da compilare che un numero indovinato.
  lines: Array<{ catalog_item: Pick<CatalogItem, 'id' | 'part_number' | 'name'> & { vendor_code: string }; is_serialized: boolean; quantity: string | null; serials: string[] }>;
  unassigned_serials: string[];
  raw_ocr_text: string;
  engine: string;
  duration_ms: number;
  // Lettura strutturale del modello: parte insieme a questa risposta e finisce
  // dopo, perché senza GPU dura minuti. Si interroga a parte.
  analysis_job_id: string | null;
}
export interface ProposedLine {
  position: string;
  description: string;
  supplier_code: string | null;
  part_number: string | null;
  quantity: string | null;
  quantity_ordered: string | null;
  catalog_item: (Pick<CatalogItem, 'id' | 'part_number' | 'name'> & { vendor_code: string }) | null;
  is_serialized: boolean | null;
  serials: string[];
  secondary_serials: string[];
  warnings: string[];
}
export interface DocumentAnalysis {
  status: 'running' | 'done' | 'failed';
  lines: ProposedLine[];
  non_goods: string[];
  unassigned_serials: string[];
  model: string;
  duration_ms: number;
  error: string | null;
}
export interface AuditEntry { id: number; ts: ISODateTime; actor_id: UUID | null; actor_username: string; action: string; entity_type: string | null; entity_id: string | null; details: Record<string, unknown>; ip_address: string | null; user_agent: string | null }
export interface AppSetting { key: string; value: unknown }
export interface HealthStatus { status: string; database?: string; extraction?: string }
export interface ReconciliationErrorRow { catalog_item_id: UUID; location_id: UUID | null; qty_ledger: string; qty_projection: string; part_number?: string | null; catalog_item_name?: string | null; location_code?: string | null }
export interface DashboardSummary { total_by_category: Array<{ category_code: string; quantity: string }>; below_reorder: StockAvailability[]; open_delivery_notes: number; recent_movements: StockMovement[]; expiring_warranties: StockUnit[]; reconciliation_errors: number; reconciliation_error_rows: ReconciliationErrorRow[] }
export interface InventoryRow { kind: 'unit' | 'bulk'; row_key: string; catalog_item_id: UUID; part_number: string; name: string; vendor_code: string; category_code: string; location_id: UUID | null; location_code: string | null; location_name: string | null; condition: ItemCondition; serial_number: string | null; mac_address: string | null; status: UnitStatus | null; delivery_note_number: string | null; warranty_end: ISODate | null; purchase_date: ISODate | null; contract_ref: string | null; notes: string | null; quantity: string | null }
export type SearchResultType = 'unit' | 'catalog_item' | 'delivery_note' | 'location';
export interface SearchResult { type: SearchResultType; id: UUID; label: string; sublabel: string | null; path: string }
export interface SearchResponse { results: SearchResult[] }

export interface TabellaInfo { nome: string; byte: number; righe_stimate: number }
export interface CopiaSulServer { nome: string; gruppo: string; byte: number; quando: number }
export interface BackupStatus {
  database: string; byte_database: number; versione_postgres: string;
  revisione_schema: string | null; versione_strumenti: string;
  tabelle: TabellaInfo[]; copie_sul_server: CopiaSulServer[]; byte_copie: number;
  disco: { totale: number; usato: number; libero: number } | null;
}
export interface RestoreResult { ok: boolean; messaggio: string; dettaglio: string; stato_precedente_ripristinato: boolean }

export interface ArchivedDocument {
  id: UUID; filename: string; byte_size: number; pages: number | null;
  // `testo` = livello di testo del PDF, `ocr` = scansione letta con l'OCR,
  // `nessuno` = non si è trovato testo. Spiega una ricerca che non trova.
  extraction_method: 'testo' | 'ocr' | 'nessuno';
  notes: string | null; delivery_note_id: UUID | null;
  delivery_note_number: string | null; uploaded_at: ISODateTime;
}
