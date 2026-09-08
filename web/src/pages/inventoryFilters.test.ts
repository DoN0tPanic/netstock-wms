import { beforeEach, describe, expect, it } from 'vitest';
import { defaultInventoryFilters, readInventoryFilters } from './inventoryFilters';

const CHIAVE = 'netstock:test-filtri';

describe('filtri del magazzino salvati sul computer', () => {
  beforeEach(() => localStorage.clear());

  it('senza niente in memoria parte dai valori vuoti', () => {
    expect(readInventoryFilters(CHIAVE)).toEqual(defaultInventoryFilters);
  });

  it('riporta alla lista un filtro salvato quando l\'ubicazione era una sola', () => {
    // Chi usava la versione precedente ha in memoria una stringa dove ora c'è
    // una lista. Senza conversione la pagina partirebbe con un filtro che non
    // è né una lista né vuoto, e il magazzino sembrerebbe vuoto.
    localStorage.setItem(CHIAVE, JSON.stringify({ q: 'sw', location: 'abc-123', page: 3 }));

    const letti = readInventoryFilters(CHIAVE);

    expect(letti.location).toEqual(['abc-123']);
    expect(letti.q).toBe('sw');
    expect(letti.page).toBe(3);
  });

  it('«nessuna ubicazione» resta nessuna, non una stringa vuota in lista', () => {
    localStorage.setItem(CHIAVE, JSON.stringify({ location: '' }));

    expect(readInventoryFilters(CHIAVE).location).toEqual([]);
  });

  it('tiene le ubicazioni multiple e butta quello che non è una stringa', () => {
    localStorage.setItem(CHIAVE, JSON.stringify({ location: ['a', '', 'b', 42, null] }));

    expect(readInventoryFilters(CHIAVE).location).toEqual(['a', 'b']);
  });

  it('memoria illeggibile: si riparte da zero invece di rompere la pagina', () => {
    localStorage.setItem(CHIAVE, 'non è json');

    expect(readInventoryFilters(CHIAVE)).toEqual(defaultInventoryFilters);
  });
});
