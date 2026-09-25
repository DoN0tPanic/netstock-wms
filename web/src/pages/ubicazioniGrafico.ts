import type { DashboardSummary } from '../types/api';

/** Quante barre prima di ripiegare la coda in una voce sola.
 *
 * Non è estetica: un magazzino con cento ubicazioni farebbe un grafico alto
 * quattromila pixel, e la domanda a cui questo grafico risponde — quali sono
 * i più carichi — ha la risposta in cima. Il resto è una riga, non cento.
 */
export const MAX_BARRE = 8;

export interface BarraUbicazione {
  location_id: string;
  location_name: string;
  quantity: number;
  sublocations: number;
  /** Vero solo per la voce che riassume le ubicazioni oltre le prime otto. */
  coda: boolean;
}

/** Le barre del grafico «Giacenza per ubicazione».
 *
 * Il server manda le ubicazioni già sommate per magazzino e in ordine di
 * quantità: qui si decide soltanto quante mostrarne per intero.
 */
export function ubicazioniDelGrafico(righe: DashboardSummary['total_by_location']): BarraUbicazione[] {
  const tutte = righe.map((riga) => ({
    location_id: riga.location_id,
    location_name: riga.location_name,
    quantity: Number(riga.quantity),
    sublocations: riga.sublocations,
    coda: false,
  }));
  if (tutte.length <= MAX_BARRE) return tutte;

  const coda = tutte.slice(MAX_BARRE);
  const quante = coda.length;
  return [
    ...tutte.slice(0, MAX_BARRE),
    {
      location_id: '__altre',
      location_name: `Altre ${quante} ubicazioni`,
      quantity: coda.reduce((somma, riga) => somma + riga.quantity, 0),
      sublocations: coda.reduce((somma, riga) => somma + riga.sublocations, 0),
      coda: true,
    },
  ];
}
