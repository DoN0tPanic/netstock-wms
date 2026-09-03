import { useState } from 'react';
import { Trash2 } from 'lucide-react';
import type { CatalogItem, ExtractionResult, ExtractionTemplate, ItemCondition, Location } from '../../types/api';
import { Button, Combobox, Input, Select } from '../ui';
import { PhotoExtract } from '../scanner/PhotoExtract';
import { SerialInput } from '../scanner/SerialInput';
import { validateSerialPattern } from '../../lib/validation';

export type Piece = { id: string; serial_number: string; mac_address?: string; location_id: string };
export type ReceiveLine = { key: string; lineId?: string; item?: CatalogItem; expected: number; condition: ItemCondition; pieces: Piece[]; quantity: number };

export const newPiece = (serial_number: string, location_id: string, mac_address?: string): Piece =>
  ({ id: crypto.randomUUID(), serial_number, location_id, ...(mac_address ? { mac_address } : {}) });

/** Forma con cui un seriale viene confrontato e salvato. */
export const normalizeSerial = (value: string) => value.trim().toUpperCase();

const conditions: ItemCondition[] = ['new', 'refurbished', 'used', 'faulty'];

/** Una riga della ricezione.
 *
 * La forma segue quello che l'operatore ha in mano: **quale modello**, **quanti
 * ne dichiara la bolla**, **quanti ne sono arrivati davvero**, e l'elenco dei
 * seriali. Quando la riga arriva dalla lettura del documento è già tutta
 * compilata: resta da controllare i seriali e correggere eventuali refusi.
 *
 * Il modello è un titolo, non una tendina, perché a quel punto è deciso: si
 * cambia solo chiedendolo. Su una riga nuova, dove non c'è ancora niente, la
 * ricerca è aperta dall'inizio.
 */
export function ReceiveLineCard({
  line, index, removable, onRemove, onChange, onSelectItem,
  catalogQuery, onCatalogQuery, catalogOptions, catalogSearching,
  locations, defaultLocationId, templates, onExtract, onApplyExtracted,
}: {
  line: ReceiveLine;
  index: number;
  removable: boolean;
  onRemove: () => void;
  onChange: (change: Partial<ReceiveLine>) => void;
  onSelectItem: (id: string) => void;
  catalogQuery: string;
  onCatalogQuery: (value: string) => void;
  catalogOptions: CatalogItem[];
  catalogSearching: boolean;
  locations: Location[];
  defaultLocationId: string;
  templates: ExtractionTemplate[];
  onExtract: (result: ExtractionResult) => void;
  onApplyExtracted: (values: Record<string, string>) => void;
}) {
  const [changingItem, setChangingItem] = useState(false);
  const serialized = Boolean(line.item?.is_serialized);
  // Su una riga serializzata "quanti ne sono arrivati" non è un numero da
  // digitare: è quanti seriali ci sono in lista. Mostrarlo come campo
  // modificabile inviterebbe a scrivere un numero che il salvataggio ignora.
  const arrivati = serialized ? line.pieces.length : line.quantity;
  const scostamento = arrivati - line.expected;

  const setPieces = (pieces: Piece[]) => onChange({ pieces });

  return (
    <article className="space-y-4 rounded-xl border bg-white p-4">
      <header className="flex flex-wrap items-start justify-between gap-3 border-b pb-3">
        <div className="min-w-0">
          <span className="text-xs uppercase tracking-wide text-slate-500">Riga {index + 1}</span>
          {line.item && !changingItem ? (
            <h3 className="text-lg font-semibold">
              <span className="font-mono">{line.item.part_number}</span>
              <span className="font-normal text-slate-600"> · {line.item.name}</span>
            </h3>
          ) : (
            <p className="text-lg font-semibold text-slate-500">Scegli il modello</p>
          )}
        </div>
        <div className="flex items-center gap-1">
          {line.item && !line.lineId && !changingItem && (
            <Button type="button" variant="ghost" onClick={() => setChangingItem(true)}>Cambia modello</Button>
          )}
          {removable && (
            <Button type="button" variant="ghost" aria-label={`Rimuovi la riga ${index + 1}`} onClick={onRemove}>
              <Trash2 size={17}/>Rimuovi
            </Button>
          )}
        </div>
      </header>

      {(!line.item || changingItem) && !line.lineId && (
        <Combobox
          label="Modello" placeholder="Cerca per part number o nome…"
          query={catalogQuery} onQueryChange={onCatalogQuery} loading={catalogSearching}
          options={catalogOptions.map((item) => ({ id: item.id, label: `${item.part_number} · ${item.name}` }))}
          selectedLabel={line.item ? `${line.item.part_number} · ${line.item.name}` : undefined}
          extraOption={{ id: '__new', label: '+ Nuovo articolo' }}
          onSelect={(id) => { onSelectItem(id); setChangingItem(false); }}
        />
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <Input
          label="Pezzi attesi" type="number" min="1" disabled={Boolean(line.lineId)}
          value={line.expected} onChange={(event) => onChange({ expected: Number(event.target.value) })}
          hint="Quanti ne dichiara la bolla."
        />
        {serialized ? (
          <div>
            <span className="mb-1 block text-sm font-medium text-slate-700">Pezzi arrivati</span>
            <p className="flex min-h-11 items-center px-1 text-lg font-semibold tabular-nums">{arrivati}</p>
            <span className="mt-1 block text-xs text-slate-500">Quanti seriali hai in lista.</span>
          </div>
        ) : (
          <Input
            label="Pezzi arrivati" type="number" min="0.01" step="any"
            value={line.quantity} onChange={(event) => onChange({ quantity: Number(event.target.value) })}
            hint="Quanti ce ne sono davvero nel collo."
          />
        )}
        <Select label="Condizione" value={line.condition} onChange={(event) => onChange({ condition: event.target.value as ItemCondition })}>
          {conditions.map((condition) => <option key={condition}>{condition}</option>)}
        </Select>
      </div>

      {line.item && scostamento !== 0 && (
        <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">
          {scostamento < 0
            ? `La bolla ne dichiara ${line.expected}, ne stai registrando ${arrivati}. Registrandola così la riga resta aperta per i ${-scostamento} mancanti: ${serialized ? 'acquisisci i seriali che mancano' : 'correggi la quantità'}, oppure correggi gli attesi se il documento sbaglia.`
            : `Ne stai registrando ${arrivati}, più dei ${line.expected} dichiarati dalla bolla: controlla prima di registrare.`}
        </p>
      )}

      {serialized && line.item && (
        <section className="space-y-3">
          <h4 className="font-semibold">Seriali</h4>
          {line.pieces.length === 0 ? (
            <p className="rounded-lg border border-dashed p-4 text-center text-sm text-slate-600">
              Nessun seriale ancora. Scansionali col lettore, inquadrali con la fotocamera o digitali qui sotto.
            </p>
          ) : (
            <ol className="space-y-2">
              {line.pieces.map((piece, position) => {
                const valore = normalizeSerial(piece.serial_number);
                const duplicato = valore !== '' && line.pieces.some((other) => other.id !== piece.id && normalizeSerial(other.serial_number) === valore);
                const fuoriFormato = valore !== '' && !validateSerialPattern(valore, line.item?.serial_pattern);
                return (
                  <li key={piece.id} className="flex items-start gap-2">
                    <span className="w-8 shrink-0 pt-2.5 text-right text-sm tabular-nums text-slate-500">{position + 1}.</span>
                    <div className="min-w-0 flex-1">
                      <Input
                        aria-label={`Seriale ${position + 1}`} value={piece.serial_number}
                        className={`font-mono uppercase ${duplicato ? 'border-red-600 bg-red-50' : fuoriFormato ? 'border-amber-500 bg-amber-50' : ''}`}
                        // Il valore si scrive così com'è battuto. Trasformarlo a
                        // ogni tasto costringe React a riscrivere il campo, e il
                        // cursore salta in fondo: correggere un carattere in
                        // mezzo — il gesto per cui questo campo esiste — diventa
                        // impossibile. Maiuscolo a vista con il CSS, forma
                        // definitiva quando si esce dal campo.
                        onChange={(event) => setPieces(line.pieces.map((old) => old.id === piece.id ? { ...old, serial_number: event.target.value } : old))}
                        onBlur={(event) => { const pulito = normalizeSerial(event.target.value); if (pulito !== piece.serial_number) setPieces(line.pieces.map((old) => old.id === piece.id ? { ...old, serial_number: pulito } : old)); }}
                        autoComplete="off" autoCorrect="off" autoCapitalize="characters" spellCheck={false}
                        error={duplicato ? 'Già presente in questa riga.' : undefined}
                        hint={!duplicato && fuoriFormato ? 'Formato inatteso per questo modello: verifica.' : piece.mac_address ? `MAC ${piece.mac_address}` : undefined}
                      />
                    </div>
                    <Button type="button" variant="ghost" aria-label={`Rimuovi il seriale ${position + 1}`} onClick={() => setPieces(line.pieces.filter((old) => old.id !== piece.id))}>
                      <Trash2 size={17}/>
                    </Button>
                  </li>
                );
              })}
            </ol>
          )}

          <SerialInput
            acquired={line.pieces.map((piece) => piece.serial_number)} expected={line.expected}
            serialPattern={line.item.serial_pattern} disabled={!defaultLocationId}
            onConfirm={(serial) => setPieces([...line.pieces, newPiece(serial, defaultLocationId)])}
          />

          {/* L'ubicazione per singolo pezzo era una tendina per ogni seriale:
              ventiquattro controlli per un'eccezione, sopra un'ubicazione
              predefinita già scelta. Sta qui, chiusa, per chi ne ha bisogno. */}
          {line.pieces.length > 0 && (
            <details className="rounded-lg border">
              <summary className="cursor-pointer px-3 py-2 text-sm font-medium">Metti qualche pezzo in un'ubicazione diversa da quella predefinita</summary>
              <div className="space-y-2 border-t p-3">
                {line.pieces.map((piece) => (
                  <div key={piece.id} className="grid items-end gap-2 sm:grid-cols-[1fr_2fr]">
                    <p className="pb-3 font-mono text-sm">{piece.serial_number || '—'}</p>
                    <Select label="Ubicazione" value={piece.location_id} onChange={(event) => setPieces(line.pieces.map((old) => old.id === piece.id ? { ...old, location_id: event.target.value } : old))}>
                      <option value="">Usa predefinita</option>
                      {locations.map((location) => <option key={location.id} value={location.id}>{location.code} · {location.name}</option>)}
                    </Select>
                  </div>
                ))}
              </div>
            </details>
          )}
        </section>
      )}

      <details className="rounded-lg border">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium">Leggi un seriale da una foto dell'etichetta</summary>
        <div className="border-t p-3">
          <PhotoExtract templates={templates} onExtract={onExtract} onApply={onApplyExtracted}/>
        </div>
      </details>
    </article>
  );
}
