import { useQuery } from '@tanstack/react-query';
import { catalogApi, categoriesApi, deliveryNotesApi, inventoryApi, locationsApi, movementsApi, suppliersApi, systemApi, vendorsApi } from '.';
export type MovementQuery = { type?: string; location?: string; reference?: string; date_from?: string; date_to?: string; page?: number; page_size?: number };
// The endpoint has no `sort` param — it always returns newest first.
export const useMovements = (query: MovementQuery = {}) => useQuery({ queryKey: ['movements', query], queryFn: () => movementsApi.list({ page_size: 50, ...query }) });
export const useDeliveryNotes = () => useQuery({ queryKey: ['delivery-notes'], queryFn: () => deliveryNotesApi.list() });
// These three feed dropdowns as well as their own pages, so they must not stop
// at the default page of 50 — a location missing from the list is invisible,
// not obviously truncated.
export const useCatalog = () => useQuery({ queryKey: ['catalog'], queryFn: () => catalogApi.list({ page_size: 200 }) });
export const useLocations = () => useQuery({ queryKey: ['locations'], queryFn: () => locationsApi.list({ page_size: 200 }) });
export const useSuppliers = () => useQuery({ queryKey: ['suppliers'], queryFn: () => suppliersApi.list({ page_size: 200 }) });
export type InventoryQuery = { q?: string; location?: string; vendor?: string; category?: string; condition?: string; status?: string; delivery_note?: string; page?: number; page_size?: number };
export const useInventory = (query: InventoryQuery) => useQuery({ queryKey: ['inventory', query], queryFn: () => inventoryApi.list(query) });
export const useVendors = () => useQuery({ queryKey: ['vendors'], queryFn: () => vendorsApi.list({ page_size: 200 }) });
export const useCategories = () => useQuery({ queryKey: ['categories'], queryFn: () => categoriesApi.list({ page_size: 200 }) });
export const useDashboard = () => useQuery({ queryKey: ['dashboard'], queryFn: () => systemApi.dashboard() });
