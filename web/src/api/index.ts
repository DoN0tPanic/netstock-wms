import { ApiError, apiDownload, apiRequest } from './client';
import type { AdjustRequest, AppSetting, ArchivedDocument, BackupStatus, RestoreResult, StatoAi, AuditEntry, AuthMe, CatalogItem, CatalogItemWrite, Category, CategoryWrite, ChangePasswordRequest, DashboardSummary, DeliveryNote, DeliveryNoteCreate, DeliveryNoteExtractionResult, DeliveryNoteLine, DocumentAnalysis, ExtractionResult, ExtractionTemplate, ExtractionTemplateWrite, FreeReceiveRequest, FreeReceiveResponse, HealthStatus, InventoryRow, IssueRequest, Location, LocationWrite, LoginRequest, Page, ReceiveRequest, ReceiveResponse, ReturnRequest, RmaMoveRequest, ScrapRequest, SearchResponse, StockAvailability, StockMovement, StockUnit, Supplier, SupplierWrite, TransferRequest, User, UserDeleteResult, Vendor, VendorWrite } from '../types/api';

type Query = Record<string, string | number | boolean | null | undefined>;
const crud = <T, W>(resource: string) => ({
  list: (query: Query = {}) => apiRequest<Page<T>>(`/${resource}`, { query }),
  create: (body: W) => apiRequest<T>(`/${resource}`, { method: 'POST', body }),
  get: (id: string) => apiRequest<T>(`/${resource}/${id}`),
  update: (id: string, body: Partial<W>) => apiRequest<T>(`/${resource}/${id}`, { method: 'PATCH', body }),
  deactivate: (id: string) => apiRequest<T>(`/${resource}/${id}/deactivate`, { method: 'POST' }),
  // Consentito solo su voci che nulla referenzia ancora; altrimenti l'API
  // risponde spiegando di disattivarla.
  remove: (id: string) => apiRequest<void>(`/${resource}/${id}`, { method: 'DELETE' }),
});

export const authApi = {
  login: (body: LoginRequest) => apiRequest<AuthMe>('/auth/login', { method: 'POST', body }),
  logout: () => apiRequest<void>('/auth/logout', { method: 'POST' }),
  me: () => apiRequest<AuthMe>('/auth/me'),
  changePassword: (body: ChangePasswordRequest) => apiRequest<void>('/auth/change-password', { method: 'POST', body }),
};
export const vendorsApi = crud<Vendor, VendorWrite>('vendors');
export const categoriesApi = crud<Category, CategoryWrite>('categories');
export const suppliersApi = crud<Supplier, SupplierWrite>('suppliers');
export const locationsApi = crud<Location, LocationWrite>('locations');
export const catalogApi = crud<CatalogItem, CatalogItemWrite>('catalog-items');
export const deliveryNotesApi = {
  list: (query: Query = {}) => apiRequest<Page<DeliveryNote>>('/delivery-notes', { query }), create: (body: DeliveryNoteCreate) => apiRequest<DeliveryNote>('/delivery-notes', { method: 'POST', body }), get: (id: string) => apiRequest<DeliveryNote>(`/delivery-notes/${id}`), update: (id: string, body: Partial<DeliveryNoteCreate>) => apiRequest<DeliveryNote>(`/delivery-notes/${id}`, { method: 'PATCH', body }), addLine: (id: string, body: DeliveryNoteCreate['lines'][number]) => apiRequest<DeliveryNoteLine>(`/delivery-notes/${id}/lines`, { method: 'POST', body }), receive: (id: string, body: ReceiveRequest, idempotencyKey?: string) => apiRequest<ReceiveResponse>(`/delivery-notes/${id}/receive`, { method: 'POST', body, idempotencyKey }), close: (id: string, reason: string) => apiRequest<DeliveryNote>(`/delivery-notes/${id}/close`, { method: 'POST', body: { reason } }), remove: (id: string) => apiRequest<void>(`/delivery-notes/${id}`, { method: 'DELETE' }),
};
export const unitsApi = { list: (query: Query = {}) => apiRequest<Page<StockUnit>>('/units', { query }), get: (id: string) => apiRequest<StockUnit>(`/units/${id}`), update: (id: string, body: Pick<Partial<StockUnit>, 'serial_number' | 'mac_address' | 'notes' | 'warranty_end' | 'contract_ref'>) => apiRequest<StockUnit>(`/units/${id}`, { method: 'PATCH', body }), bySerial: (serial: string) => apiRequest<StockUnit>(`/units/by-serial/${encodeURIComponent(serial)}`), movements: (id: string) => apiRequest<StockMovement[]>(`/units/${id}/movements`), attachDeliveryNote: (id: string, deliveryNoteId: string) => apiRequest<StockUnit>(`/units/${id}/attach-delivery-note`, { method: 'POST', body: { delivery_note_id: deliveryNoteId } }) };
export const stockApi = { list: (query: Query = {}) => apiRequest<StockAvailability[]>('/stock', { query }), export: (format: 'csv' | 'xlsx') => apiDownload('/stock/export', { format }) };
export const inventoryApi = { list: (query: Query = {}) => apiRequest<Page<InventoryRow>>('/inventory', { query }), export: (format: 'csv' | 'xlsx', query: Query = {}) => apiDownload('/inventory/export', { ...query, format }) };
// L'archivio completo: un solo scarico invece di sette pagine da visitare.
export const exportApi = { everything: () => apiDownload('/export', {}) };
// Archivio dei documenti: ricerca propria, separata da quella globale.
export const documentsApi = {
  list: (query: Query = {}) => apiRequest<Page<ArchivedDocument>>('/documents', { query }),
  upload: (file: File, note?: string, deliveryNoteId?: string) => { const body = new FormData(); body.append('file', file); if (note) body.append('note', note); if (deliveryNoteId) body.append('delivery_note_id', deliveryNoteId); return apiRequest<ArchivedDocument>('/documents', { method: 'POST', body }); },
  text: (id: string) => apiRequest<{ id: string; filename: string; extraction_method: string; text: string }>(`/documents/${id}/testo`),
  remove: (id: string) => apiRequest<void>(`/documents/${id}`, { method: 'DELETE' }),
  fileUrl: (id: string) => `/api/v1/documents/${id}/file`,
};
export const searchApi = { search: (q: string) => apiRequest<SearchResponse>('/search', { query: { q } }) };
export const movementsApi = {
  list: (query: Query = {}) => apiRequest<Page<StockMovement>>('/movements', { query }), receive: (body: FreeReceiveRequest) => apiRequest<FreeReceiveResponse>('/movements/receive', { method: 'POST', body }), issue: (body: IssueRequest) => apiRequest<StockMovement[]>('/movements/issue', { method: 'POST', body }), transfer: (body: TransferRequest) => apiRequest<StockMovement[]>('/movements/transfer', { method: 'POST', body }), returnItems: (body: ReturnRequest) => apiRequest<StockMovement[]>('/movements/return', { method: 'POST', body }), rmaOut: (body: RmaMoveRequest) => apiRequest<StockMovement[]>('/movements/rma-out', { method: 'POST', body }), rmaIn: (body: RmaMoveRequest) => apiRequest<StockMovement[]>('/movements/rma-in', { method: 'POST', body }), adjust: (body: AdjustRequest) => apiRequest<StockMovement>('/movements/adjust', { method: 'POST', body }), scrap: (body: ScrapRequest) => apiRequest<StockMovement>('/movements/scrap', { method: 'POST', body }), reverse: (id: string, reason: string) => apiRequest<StockMovement>(`/movements/${id}/reverse`, { method: 'POST', body: { reason } }), export: (format: 'csv' | 'xlsx', dateFrom?: string, dateTo?: string) => apiDownload('/movements/export', { format, date_from: dateFrom, date_to: dateTo }),
};
export const extractionApi = {
  extract: (files: File[], templateId?: string, hintCategory?: string) => { const body = new FormData(); files.forEach((file) => body.append('images', file)); if (templateId) body.append('template_id', templateId); if (hintCategory) body.append('hint_category', hintCategory); return apiRequest<ExtractionResult>('/extract', { method: 'POST', body }); },
  extractDeliveryNote: (files: File[], templateId?: string) => { const body = new FormData(); files.forEach((file) => body.append('images', file)); if (templateId) body.append('template_id', templateId); return apiRequest<DeliveryNoteExtractionResult>('/extract/delivery-note', { method: 'POST', body }); },
  deliveryNoteAnalysis: (jobId: string) => apiRequest<DocumentAnalysis>(`/extract/delivery-note/analysis/${jobId}`),
  // Segnala che la proposta è stata portata nel modulo. Non blocca niente e
  // non si fa notare: se fallisce, si perde una misura, non un'operazione.
  esito: (runId: string, accepted: boolean) => apiRequest<void>(`/extract/runs/${runId}/esito`, { method: 'POST', body: { accepted } }).catch(() => undefined),
  templates: { list: () => apiRequest<ExtractionTemplate[]>('/extraction-templates'), create: (body: ExtractionTemplateWrite) => apiRequest<ExtractionTemplate>('/extraction-templates', { method: 'POST', body }), update: (id: string, body: Partial<ExtractionTemplateWrite>) => apiRequest<ExtractionTemplate>(`/extraction-templates/${id}`, { method: 'PATCH', body }), test: (id: string, files: File[], fieldSpecs: ExtractionTemplateWrite['field_specs']) => { const body = new FormData(); files.forEach((file) => body.append('images', file)); body.append('field_specs', JSON.stringify(fieldSpecs)); return apiRequest<ExtractionResult>(`/extraction-templates/${id}/test`, { method: 'POST', body }); } }
};
// The create body is `initial_password`, not `password` — it must match
// UserCreate in api/app/schemas/users.py or the request is rejected with 422.
export const usersApi = { list: (query: Query = {}) => apiRequest<Page<User>>('/users', { query }), create: (body: Pick<User, 'username' | 'full_name' | 'role'> & { email?: string | null; initial_password: string }) => apiRequest<User>('/users', { method: 'POST', body }), update: (id: string, body: Partial<Pick<User, 'full_name' | 'email' | 'role' | 'is_active'>>) => apiRequest<User>(`/users/${id}`, { method: 'PATCH', body }), resetPassword: (id: string) => apiRequest<{ temporary_password: string }>(`/users/${id}/reset-password`, { method: 'POST' }), remove: (id: string) => apiRequest<UserDeleteResult>(`/users/${id}`, { method: 'DELETE' }), purge: (id: string) => apiRequest<UserDeleteResult>(`/users/${id}/permanent`, { method: 'DELETE' }), restore: (id: string) => apiRequest<{ temporary_password: string }>(`/users/${id}/restore`, { method: 'POST' }) };
export const adminApi = { audit: (query: Query = {}) => apiRequest<Page<AuditEntry>>('/audit', { query }), settings: () => apiRequest<AppSetting[]>('/settings'), updateSetting: (key: string, value: unknown) => apiRequest<AppSetting>(`/settings/${encodeURIComponent(key)}`, { method: 'PUT', body: { value } }) };
// `/metrics` non c'è: è previsto in progetto ma non ancora implementato, e
// un client che lo chiamasse prenderebbe un 404.
// La copia di sicurezza non passa da `apiDownload`: quello aspetta una GET
// senza corpo, questa è una POST che genera il file al momento.
export const maintenanceApi = {
  status: () => apiRequest<BackupStatus>('/maintenance/backup'),
  backup: async (): Promise<Blob> => {
    const risposta = await fetch('/api/v1/maintenance/backup', { method: 'POST', credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    if (!risposta.ok) throw new ApiError(risposta.status, 'BACKUP_ERROR', 'Impossibile creare la copia di sicurezza.', {});
    return risposta.blob();
  },
  restore: (file: File, conferma: string) => { const body = new FormData(); body.append('file', file); body.append('conferma', conferma); return apiRequest<RestoreResult>('/maintenance/restore', { method: 'POST', body }); },
};
export const aiApi = {
  status: () => apiRequest<StatoAi>('/ai/stato'),
  setModel: (modello: string, modalita?: string) => apiRequest<StatoAi>('/ai/modello', { method: 'PUT', body: { modello, modalita } }),
};
export const systemApi = { health: () => apiRequest<HealthStatus>('/health'), ready: () => apiRequest<HealthStatus>('/health/ready'), dashboard: () => apiRequest<DashboardSummary>('/dashboard') };
