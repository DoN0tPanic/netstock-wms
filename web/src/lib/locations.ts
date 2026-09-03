import type { Location } from '../types/api';

const FRECCIA = ' › ';

/** L'ubicazione per esteso: «Deposito Alfa › Scaffale A01».
 *
 * A schermo compariva solo il codice — `DEP-ALFA`, `001` — che è la chiave, non
 * l'informazione: dice dove andare soltanto a chi il magazzino ce l'ha già in
 * testa. Il nome da solo non basta, perché due scaffali «A01» in due magazzini
 * diversi sono legittimi e indistinguibili: quello che serve è il percorso.
 *
 * Si ricostruisce qui e non lato server perché l'elenco delle ubicazioni è già
 * caricato in ogni pagina che ne mostra una, e la gerarchia è profonda due o
 * tre livelli: una query ricorsiva per riga sarebbe costata più di così.
 */
export function percorsoUbicazione(
  locations: Location[],
  id: string | null | undefined,
  vuoto = '—',
): string {
  if (!id) return vuoto;
  const perId = new Map(locations.map((location) => [location.id, location]));
  const nomi: string[] = [];
  // `visti` non è prudenza teorica: `parent_id` è un'autoreferenza, e due
  // ubicazioni che si dichiarano genitore a vicenda bloccherebbero la pagina
  // invece di mostrare un nome storto.
  const visti = new Set<string>();
  let corrente = perId.get(id);
  while (corrente && !visti.has(corrente.id)) {
    visti.add(corrente.id);
    nomi.unshift(corrente.name || corrente.code);
    corrente = corrente.parent_id ? perId.get(corrente.parent_id) : undefined;
  }
  // Se l'elenco caricato non contiene quell'ubicazione (disattivata, o oltre
  // la prima pagina) è meglio il codice del trattino: è pur sempre un
  // riferimento che qualcuno può cercare.
  return nomi.length ? nomi.join(FRECCIA) : vuoto;
}

/** Come sopra, ma per un elenco a discesa: senza il trattino di riempimento. */
export function etichettaUbicazione(locations: Location[], location: Location): string {
  return percorsoUbicazione(locations, location.id, location.name);
}
