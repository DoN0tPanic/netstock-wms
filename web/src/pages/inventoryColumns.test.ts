import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  COLONNE_MAGAZZINO,
  COLONNE_PREDEFINITE,
  leggiColonne,
  scriviColonne,
  type ColonnaMagazzino,
} from './inventoryColumns';

const CHIAVE = 'netstock:inventory-columns:prova';

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe('colonne del magazzino', () => {
  it('senza preferenza mostra la tabella com\'era', () => {
    // La richiesta era «questi siano i filtri di default»: chi apre la pagina
    // domani deve trovarla identica a ieri.
    expect(leggiColonne(CHIAVE)).toEqual(COLONNE_PREDEFINITE);
    expect(COLONNE_PREDEFINITE).not.toContain('notes');
  });

  it('ricorda la scelta', () => {
    scriviColonne(CHIAVE, ['serial', 'model', 'notes']);
    expect(leggiColonne(CHIAVE)).toEqual(['serial', 'model', 'notes']);
  });

  it('scarta una colonna che non esiste più', () => {
    // Una preferenza salvata sopravvive al codice che l'ha generata: se una
    // colonna sparisce dall'applicazione, la tabella non deve provare a
    // disegnarla.
    localStorage.setItem(CHIAVE, JSON.stringify(['serial', 'colonna-inventata']));
    expect(leggiColonne(CHIAVE)).toEqual(['serial']);
  });

  it('su una preferenza illeggibile ricade sulle predefinite', () => {
    localStorage.setItem(CHIAVE, 'non è json');
    expect(leggiColonne(CHIAVE)).toEqual(COLONNE_PREDEFINITE);
    localStorage.setItem(CHIAVE, JSON.stringify([]));
    expect(leggiColonne(CHIAVE)).toEqual(COLONNE_PREDEFINITE);
  });

  it('non si rompe se il browser non lascia memorizzare', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('bloccato'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('bloccato'); });
    expect(leggiColonne(CHIAVE)).toEqual(COLONNE_PREDEFINITE);
    expect(() => scriviColonne(CHIAVE, ['serial'])).not.toThrow();
  });

  it('il seriale non si può togliere', () => {
    // Senza, la riga non è cliccabile e non si sa di che pezzo si parli.
    const fisse = COLONNE_MAGAZZINO.filter((colonna) => colonna.sempre).map((c) => c.chiave);
    expect(fisse).toEqual<ColonnaMagazzino[]>(['serial']);
  });
});
