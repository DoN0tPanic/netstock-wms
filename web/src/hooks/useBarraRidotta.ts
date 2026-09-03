import { useEffect, useState } from 'react';

const CHIAVE = 'netstock:barra-ridotta';

/** La barra laterale ridotta alle sole icone, e la scelta che se lo ricorda.
 *
 * È una preferenza di chi guarda, non un dato dell'applicazione: sta nel
 * browser di quella persona e non tocca il database. Vale per postazione,
 * che è esattamente quello che serve — su un monitor grande la barra estesa
 * ci sta, sul portatile in magazzino no.
 *
 * Il valore si legge prima del primo disegno: leggerlo dopo farebbe comparire
 * la barra intera per un istante a ogni caricamento, che è più fastidioso
 * della barra intera e basta.
 */
export function useBarraRidotta(): [boolean, () => void] {
  const [ridotta, setRidotta] = useState(() => {
    // In un browser che blocca l'archiviazione locale `localStorage` non è
    // solo vuoto: l'accesso stesso solleva. La preferenza si perde, la
    // pagina no.
    try {
      return localStorage.getItem(CHIAVE) === '1';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(CHIAVE, ridotta ? '1' : '0');
    } catch {
      // Preferenza non memorizzabile: pazienza, vale per questa sessione.
    }
  }, [ridotta]);

  return [ridotta, () => setRidotta((valore) => !valore)];
}
