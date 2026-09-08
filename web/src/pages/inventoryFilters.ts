export type InventoryFilters = {
  q: string;
  // Più ubicazioni insieme: in un magazzino vero la domanda è «quanti ne ho
  // fra il deposito e il CED», e con una scelta singola ci si risponde
  // facendo due ricerche e sommando a mente.
  location: string[];
  vendor: string;
  category: string;
  condition: string;
  status: string;
  page: number;
};

export const defaultInventoryFilters: InventoryFilters = {
  q: '', location: [], vendor: '', category: '', condition: '', status: '', page: 1,
};

/** I filtri salvati su questo computer, riportati alla forma di adesso.
 *
 * Chi usava la versione precedente ha in memoria una stringa sola dove ora
 * c'è una lista: senza questa conversione la pagina partirebbe con un filtro
 * che non è né una lista né vuoto, e il magazzino sembrerebbe vuoto.
 */
export function readInventoryFilters(key: string): InventoryFilters {
  try {
    const stored = JSON.parse(localStorage.getItem(key) ?? 'null') as Partial<InventoryFilters> | null;
    if (!stored) return defaultInventoryFilters;
    const grezzo: unknown = stored.location;
    const location = Array.isArray(grezzo)
      ? grezzo.filter((v): v is string => typeof v === 'string' && v !== '')
      : typeof grezzo === 'string' && grezzo !== '' ? [grezzo] : [];
    return { ...defaultInventoryFilters, ...stored, location, page: Number(stored.page) || 1 };
  } catch {
    return defaultInventoryFilters;
  }
}
