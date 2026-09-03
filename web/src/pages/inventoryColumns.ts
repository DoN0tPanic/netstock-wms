/** Quali colonne mostrare nella tabella del magazzino.
 *
 * Le predefinite sono quelle che c'erano: chi apre la pagina domani deve
 * trovarla com'era. Le altre esistono nel dato ma non nella vista — le note di
 * un pezzo interessano quando si sta cercando *quel* pezzo, non mentre si
 * scorre l'inventario, e messe in tabella per tutti stringerebbero le colonne
 * che si guardano sempre.
 *
 * La scelta è una preferenza di chi guarda, come la barra laterale ridotta:
 * sta nel suo browser, per utente, e non nel database.
 *
 * Nell'esportazione invece non si sceglie niente: esce tutto. In un file non
 * si sa chi lo aprirà né cosa cercherà, e una colonna che manca costringe a
 * rifare l'esportazione.
 */
export type ColonnaMagazzino =
  | 'serial' | 'model' | 'vendor' | 'category' | 'location' | 'condition'
  | 'state' | 'note' | 'warranty' | 'purchase' | 'contract' | 'notes';

export const COLONNE_MAGAZZINO: { chiave: ColonnaMagazzino; etichetta: string; sempre?: boolean }[] = [
  // Il seriale è il pezzo: senza, la riga non è cliccabile e non si sa di
  // cosa si stia parlando. È l'unica che non si può togliere.
  { chiave: 'serial', etichetta: 'Seriale / MAC', sempre: true },
  { chiave: 'model', etichetta: 'Modello' },
  { chiave: 'vendor', etichetta: 'Fornitore' },
  { chiave: 'category', etichetta: 'Categoria' },
  { chiave: 'location', etichetta: 'Ubicazione' },
  { chiave: 'condition', etichetta: 'Condizione' },
  { chiave: 'state', etichetta: 'Stato / Quantità' },
  { chiave: 'note', etichetta: 'Bolla' },
  { chiave: 'warranty', etichetta: 'Garanzia' },
  { chiave: 'purchase', etichetta: 'Data acquisto' },
  { chiave: 'contract', etichetta: 'Riferimento contratto' },
  { chiave: 'notes', etichetta: 'Note' },
];

export const COLONNE_PREDEFINITE: ColonnaMagazzino[] = [
  'serial', 'model', 'vendor', 'category', 'location', 'condition', 'state', 'note',
];

export function leggiColonne(chiave: string): ColonnaMagazzino[] {
  try {
    const salvate = JSON.parse(localStorage.getItem(chiave) ?? 'null') as unknown;
    if (!Array.isArray(salvate)) return COLONNE_PREDEFINITE;
    // Si filtra su quelle note: una colonna tolta dal codice resterebbe
    // altrimenti nella preferenza di chi l'aveva scelta, e la tabella
    // proverebbe a disegnare una colonna che non esiste più.
    const valide = salvate.filter((voce): voce is ColonnaMagazzino =>
      COLONNE_MAGAZZINO.some((colonna) => colonna.chiave === voce));
    return valide.length ? valide : COLONNE_PREDEFINITE;
  } catch {
    return COLONNE_PREDEFINITE;
  }
}

export function scriviColonne(chiave: string, colonne: ColonnaMagazzino[]): void {
  try {
    localStorage.setItem(chiave, JSON.stringify(colonne));
  } catch {
    // Preferenza non memorizzabile: vale per questa sessione.
  }
}
