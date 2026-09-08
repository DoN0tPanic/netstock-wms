import { useQuery } from '@tanstack/react-query';
import type { Page } from '../types/api';
import { tutteLeVoci } from './tendina';
import { catalogApi, categoriesApi, deliveryNotesApi, inventoryApi, locationsApi, movementsApi, suppliersApi, systemApi, vendorsApi } from '.';
export type MovementQuery = { type?: string; location?: string[]; reference?: string; date_from?: string; date_to?: string; page?: number; page_size?: number };
// The endpoint has no `sort` param — it always returns newest first.
export const useMovements = (query: MovementQuery = {}) => useQuery({ queryKey: ['movements', query], queryFn: () => movementsApi.list({ page_size: 50, ...query }) });
export type DeliveryNoteQuery = { page?: number; page_size?: number };
export const useDeliveryNotes = (query: DeliveryNoteQuery = {}) => useQuery({ queryKey: ['delivery-notes', query], queryFn: () => deliveryNotesApi.list({ page_size: 50, ...query }) });
// Questi elenchi riempiono le tendine oltre che le proprie pagine, quindi
// devono arrivare interi: una voce mancante non sembra troncata, sembra
// inesistente. Duecento era comunque un tetto — sotto ci si stava, ma
// silenziosamente; ora si scorre finché il server non ha finito.
const paginaIntera = <T,>(voci: T[]): Page<T> => ({ items: voci, total: voci.length, page: 1, page_size: voci.length });
export const useCatalog = () => useQuery({ queryKey: ['catalog'], queryFn: async () => paginaIntera(await tutteLeVoci((q) => catalogApi.list(q))) });
export const useLocations = () => useQuery({ queryKey: ['locations'], queryFn: async () => paginaIntera(await tutteLeVoci((q) => locationsApi.list(q))) });
export const useSuppliers = () => useQuery({ queryKey: ['suppliers'], queryFn: async () => paginaIntera(await tutteLeVoci((q) => suppliersApi.list(q))) });
export type InventoryQuery = { q?: string; location?: string[]; vendor?: string; category?: string; condition?: string; status?: string; delivery_note?: string; page?: number; page_size?: number };
export const useInventory = (query: InventoryQuery) => useQuery({ queryKey: ['inventory', query], queryFn: () => inventoryApi.list(query) });
export const useVendors = () => useQuery({ queryKey: ['vendors'], queryFn: async () => paginaIntera(await tutteLeVoci((q) => vendorsApi.list(q))) });
export const useCategories = () => useQuery({ queryKey: ['categories'], queryFn: async () => paginaIntera(await tutteLeVoci((q) => categoriesApi.list(q))) });
export const useDashboard = () => useQuery({ queryKey: ['dashboard'], queryFn: () => systemApi.dashboard() });
