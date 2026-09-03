import { describe, expect, it } from 'vitest';
import type { Location } from '../types/api';
import { percorsoUbicazione } from './locations';

const ubicazione = (id: string, code: string, name: string, parent_id: string | null = null) =>
  ({ id, code, name, parent_id, type: 'shelf', address: null, is_active: true,
     created_at: '', updated_at: '' }) as Location;

const magazzino = ubicazione('1', 'DEP-ALFA', 'Deposito Alfa');
const scaffale = ubicazione('2', 'DEP-ALFA-A01', 'Scaffale A01', '1');
const scatola = ubicazione('3', 'DEP-ALFA-A01-B7', 'Contenitore B7', '2');

describe('percorsoUbicazione', () => {
  it('mostra il percorso completo, non il codice della foglia', () => {
    expect(percorsoUbicazione([magazzino, scaffale, scatola], '3'))
      .toBe('Deposito Alfa › Scaffale A01 › Contenitore B7');
  });

  it('su un\'ubicazione senza genitore resta il suo nome', () => {
    expect(percorsoUbicazione([magazzino], '1')).toBe('Deposito Alfa');
  });

  it('senza ubicazione dice quello che si vuole', () => {
    expect(percorsoUbicazione([magazzino], null)).toBe('—');
    expect(percorsoUbicazione([magazzino], undefined, 'esterno')).toBe('esterno');
  });

  it('se l\'ubicazione non è nell\'elenco non inventa niente', () => {
    // Può succedere: disattivata, oppure oltre la pagina caricata.
    expect(percorsoUbicazione([magazzino], 'sconosciuta')).toBe('—');
  });

  it('non si blocca se due ubicazioni si dichiarano genitore a vicenda', () => {
    const a = ubicazione('a', 'A', 'Prima', 'b');
    const b = ubicazione('b', 'B', 'Seconda', 'a');
    expect(percorsoUbicazione([a, b], 'a')).toBe('Seconda › Prima');
  });
});
