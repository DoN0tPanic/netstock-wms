import { beforeEach, describe, expect, it } from 'vitest';
import { defaultInventoryFilters, readInventoryFilters } from './inventoryFilters';

describe('persistenza filtri giacenze', () => {
  beforeEach(() => localStorage.clear());
  it('ripristina i filtri salvati per la chiave utente', () => {
    localStorage.setItem('netstock:inventory-filters:mario', JSON.stringify({ q: 'switch', status: 'in_stock', page: 3 }));
    expect(readInventoryFilters('netstock:inventory-filters:mario')).toEqual({ ...defaultInventoryFilters, q: 'switch', status: 'in_stock', page: 3 });
    expect(readInventoryFilters('netstock:inventory-filters:anna')).toEqual(defaultInventoryFilters);
  });
  it('usa i valori predefiniti se lo storage non contiene JSON valido', () => {
    localStorage.setItem('netstock:inventory-filters:mario', '{');
    expect(readInventoryFilters('netstock:inventory-filters:mario')).toEqual(defaultInventoryFilters);
  });
});
