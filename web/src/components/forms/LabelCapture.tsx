import { useEffect, useRef, useState } from 'react';
import { Camera, Check, PackagePlus, ScanBarcode, X } from 'lucide-react';
import { extractionApi } from '../../api';
import type { CatalogItem, ExtractionTemplate } from '../../types/api';
import { Badge, Busy, Button, Combobox, Input, Modal } from '../ui';
import { EXTRACTION_FILE_ACCEPT, prepareExtractionImage } from '../scanner/PhotoExtract';
import { BarcodeCamera } from '../scanner/BarcodeCamera';

/** Quello che l'etichetta ha detto. `item` è il **riferimento** all'articolo
 *  riconosciuto, non l'articolo intero: l'estrazione restituisce solo codice e
 *  nome, e fingere che sia un `CatalogItem` completo faceva credere alla riga
 *  che l'articolo non fosse serializzato — quindi niente elenco dei seriali. */
export type LabelReading = {
  part_number: string;
  serial_number: string;
  mac_address: string;
  item: { id: string; part_number: string; name: string } | null;
};

const valueOf = (fields: Record<string, { value: string }>, ...names: string[]) => {
  for (const name of names) {
    const found = fields[name]?.value?.trim();
    if (found) return found;
  }
  return '';
};

/** Inserimento a raffica fotografando le etichette, pensato per il telefono.
 *
 * È il percorso principale quando la merce arriva **senza bolla**: non c'è un
 * documento da cui partire, e riscrivere modello e seriale a mano su una
 * tastiera virtuale, pezzo per pezzo, è il modo più lento e più sbagliabile di
 * riempire un magazzino.
 *
 * Resta la regola di sempre: quello che l'etichetta dice viene **proposto**, si
 * vede prima di accettarlo ed è modificabile. Qui in più il ciclo si richiude
 * da solo — accettato un pezzo, la fotocamera è già pronta per il successivo,
 * che è quello che serve quando se ne hanno venti da censire.
 */
export function LabelCapture({
  templates, disabled, disabledReason, onAdd, onCreateItem, addedSignal = 0,
  catalogQuery, onCatalogQuery, catalogOptions, catalogSearching,
}: {
  templates: ExtractionTemplate[];
  catalogQuery: string;
  onCatalogQuery: (value: string) => void;
  catalogOptions: CatalogItem[];
  catalogSearching: boolean;
  disabled?: boolean;
  disabledReason?: string;
  /** Cresce quando il pezzo è stato aggiunto dal genitore — succede dopo aver
   *  creato l'articolo a catalogo, dove l'aggiunta non parte da qui. */
  addedSignal?: number;
  onAdd: (reading: LabelReading) => Promise<{ ok: true } | { ok: false; motivo: string }>;
  onCreateItem: (reading: LabelReading) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [esito, setEsito] = useState('');
  const [letto, setLetto] = useState<LabelReading | null>(null);
  // La lettura da cui viene quello che si sta guardando. Serve solo a
  // registrarne l'esito: senza, nessuno può dire se l'estrazione automatica
  // faccia risparmiare tempo o sia soltanto un container acceso.
  const [lettura, setLettura] = useState<string | null>(null);
  const [conteggio, setConteggio] = useState(0);
  const [scanner, setScanner] = useState(false);
  const [daBarcode, setDaBarcode] = useState(false);
  // Il modello dell'ultimo pezzo accettato. Serve al caso più comune di tutti:
  // venti apparati identici da censire. Si sceglie una volta, poi si scansiona
  // e basta — senza rifotografare l'etichetta di ognuno per scoprire un modello
  // che si conosce già.
  const [ultimoModello, setUltimoModello] = useState<LabelReading['item']>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const visto = useRef(addedSignal);

  useEffect(() => {
    if (addedSignal === visto.current) return;
    visto.current = addedSignal;
    setConteggio((valore) => valore + 1);
    setEsito('Pezzo aggiunto.');
    setLetto(null); setError('');
  }, [addedSignal]);

  const leggi = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true); setError(''); setEsito(''); setDaBarcode(false);
    try {
      const prepared = await prepareExtractionImage(files[0]!);
      const risultato = await extractionApi.extract([prepared]);
      setLettura(risultato.run_id);
      const matched = risultato.matched_catalog_item;
      setLetto({
        part_number: valueOf(risultato.fields, 'part_number') || matched?.part_number || '',
        serial_number: valueOf(risultato.fields, 'serial_number', 'serial'),
        mac_address: valueOf(risultato.fields, 'mac_address', 'mac'),
        item: matched ? { id: matched.id, part_number: matched.part_number, name: matched.name } : null,
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Lettura non riuscita. Riprova, o inserisci a mano.');
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = '';
    }
  };

  const accetta = async () => {
    if (!letto) return;
    setBusy(true);
    const risposta = await onAdd(letto);
    setBusy(false);
    if (!risposta.ok) { setError(risposta.motivo); return; }
    // Il pezzo è entrato in magazzino partendo da quello che il modello ha
    // letto: è il momento in cui quella lettura è servita a qualcosa.
    if (lettura) { void extractionApi.esito(lettura, true); setLettura(null); }
    setUltimoModello(letto.item);
    setConteggio((valore) => valore + 1);
    setEsito(`${letto.serial_number || 'Pezzo'} aggiunto.`);
    setLetto(null); setError('');
    // Si riparte da soli col mezzo appena usato: la fotocamera se si stava
    // fotografando, lo scanner se si stava scansionando. Chi censisce venti
    // pezzi non deve ritrovare il pulsante ogni volta.
    if (daBarcode) setScanner(true); else inputRef.current?.click();
  };

  /** Un barcode letto diventa il seriale del pezzo in corso; se non ce n'è uno,
   *  ne apre uno nuovo già sul modello dell'ultimo accettato. */
  const barcodeLetto = (valore: string) => {
    setScanner(false);
    const serial = valore.trim().toUpperCase();
    if (!serial) return;
    setError(''); setEsito('');
    setDaBarcode(true);
    setLetto((corrente) => corrente
      ? { ...corrente, serial_number: serial }
      : { part_number: ultimoModello?.part_number ?? '', serial_number: serial, mac_address: '', item: ultimoModello });
  };

  return (
    <section className="space-y-3 rounded-xl border border-blue-200 bg-blue-50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 font-semibold"><Camera size={19}/>Fotografa l'etichetta</h3>
          <p className="text-sm text-slate-700">
            Inquadra il barcode per il solo seriale, oppure fotografa l'etichetta per leggere
            anche modello e MAC. Quello che esce viene proposto: controlli e confermi.
            {conteggio > 0 && <> Finora ne hai aggiunti <strong>{conteggio}</strong>.</>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="secondary" disabled={disabled || busy} onClick={() => setScanner(true)}>
            <ScanBarcode size={19}/>Inquadra il barcode
          </Button>
          <label className={`inline-flex min-h-11 items-center gap-2 rounded-lg px-4 py-2 font-medium text-white ${disabled || busy ? 'cursor-not-allowed bg-slate-400' : 'cursor-pointer bg-blue-600 hover:bg-blue-700'}`}>
            <Camera size={19}/>{letto ? 'Rifai la foto' : 'Fotografa'}
            <input ref={inputRef} className="sr-only" type="file" accept={EXTRACTION_FILE_ACCEPT}
              capture="environment" disabled={disabled || busy}
              onChange={(event) => void leggi(event.target.files)}/>
          </label>
        </div>
      </div>

      {disabled && disabledReason && <p className="text-sm text-slate-700">{disabledReason}</p>}
      {busy && <Busy title="Sto leggendo l'etichetta…">Di norma bastano un paio di secondi.</Busy>}
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{error}</p>}
      {esito && !letto && <p role="status" className="flex items-center gap-2 rounded-lg bg-green-50 p-3 text-sm text-green-800"><Check size={17}/>{esito}</p>}

      {letto && (
        <div className="space-y-3 rounded-lg border bg-white p-3">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="font-mono">{letto.part_number || '—'}</strong>
            {letto.item
              ? <Badge tone="success">A catalogo: {letto.item.name}</Badge>
              : <Badge tone="warning">Non a catalogo</Badge>}
          </div>
          {!letto.item && (
            <Combobox label="Modello" placeholder="Cerca per part number o nome…"
              query={catalogQuery} onQueryChange={onCatalogQuery} loading={catalogSearching}
              options={catalogOptions.map((item) => ({ id: item.id, label: `${item.part_number} · ${item.name}` }))}
              onSelect={(id) => { const scelto = catalogOptions.find((item) => item.id === id); if (scelto) setLetto({ ...letto, item: { id: scelto.id, part_number: scelto.part_number, name: scelto.name }, part_number: scelto.part_number }); }}
              hint="Scansionando il barcode il modello non si sa: scegli il primo, poi resta per i successivi."/>
          )}
          <div className="flex items-end gap-2">
          <div className="min-w-0 flex-1">
          <Input label="Numero seriale" value={letto.serial_number} className="font-mono"
            autoComplete="off" autoCorrect="off" autoCapitalize="characters" spellCheck={false}
            onChange={(event) => setLetto({ ...letto, serial_number: event.target.value })}
            hint="Correggi qui, oppure rileggilo col barcode."/>
          </div>
          <Button type="button" variant="secondary" className="mb-[1.375rem] shrink-0" onClick={() => setScanner(true)}><ScanBarcode size={18}/>Rileggi</Button>
          </div>
          {letto.mac_address && (
            <Input label="MAC address" value={letto.mac_address} className="font-mono"
              onChange={(event) => setLetto({ ...letto, mac_address: event.target.value })}/>
          )}
          <div className="flex flex-wrap gap-2">
            {letto.item
              ? <Button type="button" onClick={() => void accetta()} disabled={!letto.serial_number.trim() || busy}><Check size={18}/>Aggiungi e scatta il prossimo</Button>
              : <Button type="button" variant="secondary" onClick={() => onCreateItem(letto)}><PackagePlus size={17}/>Crea l'articolo a catalogo</Button>}
            <Button type="button" variant="ghost" onClick={() => { if (lettura) { void extractionApi.esito(lettura, false); setLettura(null); } setLetto(null); setError(''); }}><X size={17}/>Scarta</Button>
          </div>
          {!letto.item && letto.part_number && (
            <p className="text-sm text-amber-800">
              Il modello letto dall'etichetta non è ancora a catalogo: crealo e poi riprendi da qui.
            </p>
          )}
        </div>
      )}
      <Modal open={scanner} title="Inquadra il barcode del seriale" onClose={() => setScanner(false)}>
        <BarcodeCamera onDetected={barcodeLetto} onClose={() => setScanner(false)}/>
      </Modal>
      {templates.length === 0 && (
        <p className="text-sm text-slate-600">Nessun template di estrazione attivo: la lettura userà solo le regole generiche.</p>
      )}
    </section>
  );
}
