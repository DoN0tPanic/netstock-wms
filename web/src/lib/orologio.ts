import type { Avviso } from '../types/api';

// Pochi secondi di differenza sono rete e arrotondamenti; due minuti sono un
// orologio sbagliato. In produzione era di due ore, e nessuno se n'era accorto.
export const SCARTO_MASSIMO_MS = 2 * 60_000;

const quanto = (ms: number) => {
  const minuti = Math.round(Math.abs(ms) / 60_000);
  return minuti >= 120 ? `${Math.round(minuti / 60)} ore` : `${minuti} minuti`;
};

/** Confronta l'ora del server con quella di questo computer, al momento della risposta. */
export function avvisoOrologio(oraServer: string, adesso: number): Avviso | null {
  const scarto = Date.parse(oraServer) - adesso;
  if (!Number.isFinite(scarto) || Math.abs(scarto) < SCARTO_MASSIMO_MS) return null;
  return {
    codice: 'orologio_scostato',
    gravita: 'attenzione',
    titolo: `L'ora del server è ${scarto > 0 ? 'avanti' : 'indietro'} di ${quanto(scarto)} rispetto a questo computer`,
    dettaglio: "Uno dei due orologi è sbagliato. Se è quello del server, ogni registrazione prende un'ora sbagliata: sul server si corregge con sudo timedatectl set-ntp true.",
  };
}
