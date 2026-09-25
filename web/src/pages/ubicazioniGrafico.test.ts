import { describe, expect, it } from 'vitest';
import { MAX_BARRE, ubicazioniDelGrafico } from './ubicazioniGrafico';
import type { DashboardSummary } from '../types/api';

const riga = (nome: string, quantita: number, sublocations = 1): DashboardSummary['total_by_location'][number] =>
  ({ location_id: `id-${nome}`, location_code: nome, location_name: nome, quantity: String(quantita), sublocations });

describe('barre del grafico per ubicazione', () => {
  it('senza giacenze non disegna niente', () => {
    expect(ubicazioniDelGrafico([])).toEqual([]);
  });

  it('fino a otto le mostra tutte, nell’ordine che arriva dal server', () => {
    const righe = Array.from({ length: MAX_BARRE }, (_, i) => riga(`Deposito ${i}`, 100 - i));
    const barre = ubicazioniDelGrafico(righe);
    expect(barre).toHaveLength(MAX_BARRE);
    expect(barre.map((b) => b.location_name)).toEqual(righe.map((r) => r.location_name));
    expect(barre.every((b) => b.coda === false)).toBe(true);
  });

  it('oltre otto ripiega la coda in una voce sola', () => {
    // Cento ubicazioni farebbero un grafico alto quattromila pixel, e la
    // domanda — quali sono i più carichi — ha la risposta in cima.
    const righe = Array.from({ length: 12 }, (_, i) => riga(`Deposito ${i}`, 100 - i));
    const barre = ubicazioniDelGrafico(righe);

    expect(barre).toHaveLength(MAX_BARRE + 1);
    const ultima = barre[MAX_BARRE]!;
    expect(ultima.coda).toBe(true);
    expect(ultima.location_name).toBe('Altre 4 ubicazioni');
  });

  it('la coda somma i pezzi che non si vedono, senza perderne nessuno', () => {
    const righe = Array.from({ length: 12 }, (_, i) => riga(`Deposito ${i}`, 100 - i));
    const barre = ubicazioniDelGrafico(righe);

    const totaleBarre = barre.reduce((somma, b) => somma + b.quantity, 0);
    const totaleVero = righe.reduce((somma, r) => somma + Number(r.quantity), 0);
    expect(totaleBarre).toBe(totaleVero);
  });

  it('le quantità arrivano come testo dal server e diventano numeri', () => {
    // Sono numerici a virgola fissa nel database, quindi JSON li manda come
    // stringhe: sommarli senza convertirli darebbe "4740" invece di 87.
    const barre = ubicazioniDelGrafico([riga('A', 47), riga('B', 40)]);
    expect(barre.map((b) => b.quantity)).toEqual([47, 40]);
    expect(barre.reduce((s, b) => s + b.quantity, 0)).toBe(87);
  });
});
