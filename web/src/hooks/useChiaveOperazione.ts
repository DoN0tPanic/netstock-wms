import { useCallback, useRef } from 'react';

/** La chiave che rende un'operazione di magazzino sicura da ripetere.
 *
 * Una per operazione, non una per clic: se la risposta del server si perde e
 * si preme di nuovo, la chiave è la stessa, e il server risponde con l'esito
 * della prima volta invece di registrare un secondo carico. Si rinnova solo
 * quando l'operazione è andata a buon fine — da lì in poi è un'altra
 * operazione, anche se i dati fossero identici (due scatole uguali di cavi,
 * arrivate una dopo l'altra, sono due carichi).
 */
export function useChiaveOperazione() {
  const chiave = useRef<string | null>(null);
  const corrente = useCallback(() => (chiave.current ??= crypto.randomUUID()), []);
  const conclusa = useCallback(() => { chiave.current = null; }, []);
  return { corrente, conclusa };
}
