import { useEffect, useState } from 'react';
import { Check, ChevronLeft, ChevronRight, Loader2, ScanLine } from 'lucide-react';
import { catalogApi, deliveryNotesApi, extractionApi, locationsApi, movementsApi, suppliersApi } from '../../api';
import { ApiError } from '../../api/client';
import type { CatalogItem, DeliveryNote, DeliveryNoteExtractionResult, DocumentAnalysis, ExtractionResult, ExtractionTemplate, FreeReceiveRequest, ItemCondition, Location, LocationType, ProposedLine, ReceiveRequest, Supplier } from '../../types/api';
import { Busy, Button, Combobox, Input, Modal, Select } from '../ui';
import { CatalogItemModal } from './CatalogItemModal';
import { DeliveryNoteProposal } from './DeliveryNoteProposal';
import { ReceiveLineCard, newPiece, normalizeSerial, type ReceiveLine } from './ReceiveLineCard';
import { LabelCapture, type LabelReading } from './LabelCapture';
import { EXTRACTION_FILE_ACCEPT, prepareExtractionImage } from '../scanner/PhotoExtract';
import { useSchermoStretto } from '../../hooks/useSchermoStretto';

type Warning = { code: string; message: string; serial_number?: string };
type PendingReceive = { kind: 'note'; noteId: string; body: ReceiveRequest } | { kind: 'free'; body: FreeReceiveRequest };
const locationTypes: LocationType[] = ['warehouse', 'shelf', 'box', 'remote_site', 'transit'];
const freshLine = (): ReceiveLine => ({ key: crypto.randomUUID(), expected: 1, condition: 'new', pieces: [], quantity: 1 });
const today = () => new Date().toISOString().slice(0, 10);
// Extraction returns the date as a literal OCR substring (e.g. "27/08/2026"),
// but the native <input type="date"> silently renders empty for anything
// that isn't ISO "YYYY-MM-DD" — without this it looked like extraction had
// failed to find the date at all.
const toIsoDate = (raw: string | undefined): string | undefined => {
  const match = raw?.match(/^([0-3]?\d)[/-]([0-1]?\d)[/-](\d{2,4})$/);
  if (!match) return undefined;
  const d = match[1]!, m = match[2]!, y = match[3]!;
  const year = y.length === 2 ? `20${y}` : y;
  const day = d.padStart(2, '0');
  const month = m.padStart(2, '0');
  const iso = `${year}-${month}-${day}`;
  return Number.isNaN(new Date(iso).getTime()) ? undefined : iso;
};
const merge = <T extends { id: string }>(a: T[], b: T[]) => [...new Map([...a, ...b].map((v) => [v.id, v])).values()];
// Su telefono la pagina non è una pagina: è un percorso. Le stesse sezioni,
// una schermata per volta, perché tre schermate di scorrimento con il pulsante
// finale in fondo sono il modo più sicuro di perdersi a metà di una bolla.
// Su scrivania resta tutto visibile insieme, come prima.
const PASSI = ['Bolla', 'Ubicazione', 'Righe', 'Conferma'];
const messageOf = (reason: unknown) => reason instanceof Error ? reason.message : 'Operazione non riuscita.';

export function ReceiveForm({ onSuccess }: { onSuccess: (createdUnits: number) => void }) {
  const [notes, setNotes] = useState<DeliveryNote[]>([]); const [noteMode, setNoteMode] = useState('');
  const [noteDraft, setNoteDraft] = useState({ number: '', note_date: today(), supplier_id: '', po_number: '' });
  const [suppliers, setSuppliers] = useState<Supplier[]>([]); const [supplierName, setSupplierName] = useState(''); const [showSupplier, setShowSupplier] = useState(false);
  const [lines, setLines] = useState<ReceiveLine[]>([freshLine()]); const [catalog, setCatalog] = useState<CatalogItem[]>([]); const [catalogQuery, setCatalogQuery] = useState(''); const [catalogOptions, setCatalogOptions] = useState<CatalogItem[]>([]); const [catalogSearching, setCatalogSearching] = useState(false);
  const [locations, setLocations] = useState<Location[]>([]); const [locationQuery, setLocationQuery] = useState(''); const [defaultLocationId, setDefaultLocationId] = useState(''); const [locationOptions, setLocationOptions] = useState<Location[]>([]); const [locationSearching, setLocationSearching] = useState(false);
  const [templates, setTemplates] = useState<ExtractionTemplate[]>([]);
  const [itemForLine, setItemForLine] = useState<string | null>(null);
  const [showLocation, setShowLocation] = useState(false); const [locationDraft, setLocationDraft] = useState({ name: '', type: 'shelf' as LocationType });
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [warnings, setWarnings] = useState<Warning[]>([]); const [pending, setPending] = useState<PendingReceive | null>(null);
  const [scanningNote, setScanningNote] = useState(false); const [noteExtraction, setNoteExtraction] = useState<DeliveryNoteExtractionResult | null>(null); const [unassigned, setUnassigned] = useState<string[]>([]); const [serialTarget, setSerialTarget] = useState<Record<string, string>>({});
  const [proposalNotices, setProposalNotices] = useState<string[]>([]);
  const [analysisJobId, setAnalysisJobId] = useState<string | null>(null); const [analysis, setAnalysis] = useState<DocumentAnalysis | null>(null); const [itemFromProposal, setItemFromProposal] = useState<ProposedLine | null>(null);
  const [labelReading, setLabelReading] = useState<LabelReading | null>(null); const [labelAdded, setLabelAdded] = useState(0);
  const stretto = useSchermoStretto(); const [passo, setPasso] = useState(1);
  /** Cosa si vede adesso: su scrivania tutto, su telefono il passo corrente. */
  const vedi = (numero: number) => !stretto || passo === numero;

  useEffect(() => { void Promise.all([deliveryNotesApi.list({ is_closed: false }).then((p) => setNotes(p.items)), suppliersApi.list({ page_size: 200 }).then((p) => setSuppliers(p.items)), locationsApi.list({ page_size: 200 }).then((p) => setLocations(p.items)), extractionApi.templates.list().then(setTemplates)]).catch((r) => setError(messageOf(r))); }, []);
  useEffect(() => { setCatalogSearching(true); const timer = window.setTimeout(() => void catalogApi.list({ q: catalogQuery || undefined, page_size: 8 }).then((p) => { setCatalogOptions(p.items); setCatalog((old) => merge(old, p.items)); }).catch((r) => setError(messageOf(r))).finally(() => setCatalogSearching(false)), 300); return () => window.clearTimeout(timer); }, [catalogQuery]);
  useEffect(() => { setLocationSearching(true); const timer = window.setTimeout(() => void locationsApi.list({ q: locationQuery || undefined, page_size: 8 }).then((p) => { setLocationOptions(p.items); setLocations((old) => merge(old, p.items)); }).catch((r) => setError(messageOf(r))).finally(() => setLocationSearching(false)), 300); return () => window.clearTimeout(timer); }, [locationQuery]);

  // La lettura strutturale finisce dopo la risposta che l'ha avviata: con una
  // GPU in pochi secondi, senza in qualche minuto. Si interroga finché non è
  // pronta, senza bloccare nulla — il modulo qui sotto è già utilizzabile.
  useEffect(() => {
    if (!analysisJobId) return;
    let stopped = false;
    const poll = async () => {
      try {
        const result = await extractionApi.deliveryNoteAnalysis(analysisJobId);
        if (stopped) return;
        setAnalysis(result);
        if (result.status === 'running') window.setTimeout(() => void poll(), 2000);
      } catch {
        // Un'analisi persa (API riavviata, risultato scaduto) non è un errore
        // da mostrare: la ricezione manuale funziona lo stesso.
        if (!stopped) setAnalysis(null);
      }
    };
    void poll();
    return () => { stopped = true; };
  }, [analysisJobId]);

  const applyProposal = async (proposed: ProposedLine[]) => {
    // La proposta finisce nel modulo: è il momento in cui la lettura è
    // servita. Registrarlo è l'unico modo per sapere, fra un mese, se questa
    // parte del sistema vale il suo costo — finora `accepted` era una colonna
    // che nessuno scriveva, e le letture registrate non dicevano niente.
    if (noteExtraction?.run_id) void extractionApi.esito(noteExtraction.run_id, true);
    setBusy(true);
    const notices: string[] = [];
    try {
      const hydrated = await Promise.all(proposed.map(async (line) => {
        const id = line.catalog_item!.id;
        const item = catalog.find((known) => known.id === id) ?? await catalogApi.get(id);
        const serials = [...new Set(line.serials.map((serial) => serial.trim().toUpperCase()).filter(Boolean))];
        const quantity = Number(line.quantity ?? serials.length ?? 1) || 1;
        // Un articolo censito "a quantità" non ha dove mettere i seriali. Buttarli
        // in silenzio sarebbe il modo peggiore di dirlo: l'operatore li ha visti
        // sul documento e sullo schermo un attimo prima.
        if (!item.is_serialized && serials.length > 0) {
          notices.push(`${item.part_number}: il documento riporta ${serials.length} seriali, ma l'articolo è censito a quantità. Non verranno registrati. Per tenerli serve un articolo serializzato.`);
        }
        return { key: crypto.randomUUID(), item, expected: item.is_serialized ? Math.max(quantity, serials.length) : quantity, condition: 'new' as ItemCondition, pieces: item.is_serialized ? serials.map((serial_number) => newPiece(serial_number, defaultLocationId)) : [], quantity };
      }));
      setCatalog((old) => merge(old, hydrated.map((line) => line.item)));
      setLines(hydrated);
      setProposalNotices(notices);
      setUnassigned([]);
      if (stretto) setPasso(2);
    } catch (reason) { setError(messageOf(reason)); } finally { setBusy(false); }
  };

  const serializedLines = lines.map((line, index) => ({ line, index })).filter(({ line }) => line.item?.is_serialized);

  /** Aggiunge alla ricezione un pezzo letto da un'etichetta.
   *
   * Se per quel modello una riga c'è già, il seriale ci si aggiunge; altrimenti
   * la riga nasce qui. È la differenza fra censire venti pezzi col telefono e
   * doversi ricordare di creare la riga giusta prima di ogni scatto.
   */
  const addFromLabel = async (reading: LabelReading, itemId: string): Promise<{ ok: true } | { ok: false; motivo: string }> => {
    const serial = normalizeSerial(reading.serial_number);
    if (!serial) return { ok: false, motivo: 'Manca il numero seriale: leggilo dall\'etichetta o scrivilo a mano.' };
    if (!defaultLocationId) return { ok: false, motivo: 'Scegli prima l\'ubicazione predefinita nella sezione 2.' };
    if (lines.some((line) => line.pieces.some((piece) => normalizeSerial(piece.serial_number) === serial))) {
      return { ok: false, motivo: `Il seriale ${serial} è già in questa ricezione.` };
    }
    // L'articolo va preso intero dal catalogo: l'estrazione restituisce solo
    // codice e nome, e senza `is_serialized` la riga non saprebbe nemmeno di
    // dover chiedere dei seriali.
    let item: CatalogItem;
    try {
      item = catalog.find((known) => known.id === itemId) ?? await catalogApi.get(itemId);
    } catch (reason) {
      return { ok: false, motivo: messageOf(reason) };
    }
    const mac = reading.mac_address.trim() || undefined;
    setCatalog((old) => merge(old, [item]));
    setLines((old) => {
      const esistente = old.find((line) => line.item?.id === item.id);
      if (esistente) {
        return old.map((line) => line.key === esistente.key
          ? { ...line, pieces: [...line.pieces, newPiece(serial, defaultLocationId, mac)], expected: Math.max(line.expected, line.pieces.length + 1) }
          : line);
      }
      const nuova: ReceiveLine = { key: crypto.randomUUID(), item, expected: 1, condition: 'new', pieces: [newPiece(serial, defaultLocationId, mac)], quantity: 1 };
      // La prima riga vuota, quella creata all'apertura del modulo, viene
      // sostituita invece di restare lì a chiedere un modello.
      const soloVuota = old.length === 1 && !old[0]?.item && old[0]?.pieces.length === 0;
      return soloVuota ? [nuova] : [...old, nuova];
    });
    return { ok: true };
  };

  const updateLine = (key: string, change: Partial<ReceiveLine>) => setLines((old) => old.map((line) => line.key === key ? { ...line, ...change } : line));
  const chooseDefaultLocation = (locationId: string) => { setDefaultLocationId(locationId); setLines((old) => old.map((line) => ({ ...line, pieces: line.pieces.map((piece) => piece.location_id ? piece : { ...piece, location_id: locationId }) }))); };
  const chooseNote = async (value: string) => { setNoteMode(value); setWarnings([]); setPending(null); if (!value || value === 'new' || value === 'none') { setLines([freshLine()]); return; } setBusy(true); setError(''); try { const note = await deliveryNotesApi.get(value); const hydrated = await Promise.all((note.lines ?? []).map(async (line) => ({ key: line.id, lineId: line.id, item: await catalogApi.get(line.catalog_item_id), expected: Number(line.qty_expected), condition: line.condition, pieces: [], quantity: Math.max(0, Number(line.qty_expected) - Number(line.qty_received)) }))); setCatalog((old) => merge(old, hydrated.map((line) => line.item))); setLines(hydrated.length ? hydrated : [freshLine()]); } catch (r) { setError(messageOf(r)); } finally { setBusy(false); } };
  const selectItem = (key: string, id: string) => { if (id === '__new') setItemForLine(key); else updateLine(key, { item: catalog.find((item) => item.id === id), pieces: [] }); };
  const recognizeItem = async (key: string, result: ExtractionResult) => { if (!result.matched_catalog_item || lines.find((line) => line.key === key)?.item) return; try { const item = await catalogApi.get(result.matched_catalog_item.id); setCatalog((old) => merge(old, [item])); updateLine(key, { item }); } catch (r) { setError(messageOf(r)); } };
  const addExtracted = (key: string, values: Record<string, string>) => { const serial = values.serial_number ?? values.serial ?? values['stock_unit.serial_number']; const line = lines.find((candidate) => candidate.key === key); const normalized = serial?.trim().toUpperCase(); if (!normalized || !line || !defaultLocationId || line.pieces.some((piece) => piece.serial_number === normalized)) return; updateLine(key, { pieces: [...line.pieces, newPiece(normalized, defaultLocationId, values.mac_address ?? values.mac)] }); };
  const createSupplier = async () => { if (!supplierName.trim()) return; setBusy(true); try { const value = await suppliersApi.create({ name: supplierName.trim() }); setSuppliers((old) => merge(old, [value])); setNoteDraft((old) => ({ ...old, supplier_id: value.id })); setSupplierName(''); setShowSupplier(false); } catch (r) { setError(messageOf(r)); } finally { setBusy(false); } };
  const createLocation = async () => { if (!locationDraft.name) return; setBusy(true); try { const value = await locationsApi.create(locationDraft); setLocations((old) => merge(old, [value])); chooseDefaultLocation(value.id); setShowLocation(false); } catch (r) { setError(messageOf(r)); } finally { setBusy(false); } };
  const readDeliveryNote = async (files: FileList | null) => { if (!files?.length) return; if (files.length > 5) { setError('Puoi inviare al massimo 5 immagini.'); return; } setScanningNote(true); setError(''); try { const prepared = await Promise.all(Array.from(files).map(prepareExtractionImage)); const result = await extractionApi.extractDeliveryNote(prepared); const hydrated = await Promise.all(result.lines.map(async (suggestion) => { const item = catalog.find((known) => known.id === suggestion.catalog_item.id) ?? await catalogApi.get(suggestion.catalog_item.id); const serials = [...new Set(suggestion.serials.map((serial) => serial.trim().toUpperCase()).filter(Boolean))]; const dichiarata = Number(suggestion.quantity ?? NaN); const attesi = Number.isFinite(dichiarata) && dichiarata > 0 ? dichiarata : (serials.length || 1); return { key: crypto.randomUUID(), item, expected: attesi, condition: 'new' as ItemCondition, pieces: item.is_serialized ? serials.map((serial_number) => newPiece(serial_number, defaultLocationId)) : [], quantity: attesi }; })); setCatalog((old) => merge(old, hydrated.map((line) => line.item))); setLines(hydrated.length ? hydrated : [freshLine()]); setNoteExtraction(result); setUnassigned(result.unassigned_serials); setSerialTarget({}); setAnalysis(null); setAnalysisJobId(result.analysis_job_id); if (noteMode !== 'new') { setNoteMode('new'); } const value = (name: string) => result.fields[name]?.value?.trim(); const supplierNameFromOcr = value('supplier_name'); const supplier = suppliers.find((candidate) => candidate.name.trim().toLocaleLowerCase() === (supplierNameFromOcr ?? '').toLocaleLowerCase()); setNoteDraft((old) => ({ ...old, number: value('ddt_number') || value('delivery_note_number') || old.number, note_date: toIsoDate(value('ddt_date') || value('delivery_note_date')) || old.note_date, po_number: value('po_number') || old.po_number, supplier_id: supplierNameFromOcr ? supplier?.id ?? '' : old.supplier_id })); } catch (reason) { setError(messageOf(reason)); } finally { setScanningNote(false); } };
  const assignUnassigned = (serial: string) => { const key = serialTarget[serial]; const line = lines.find((candidate) => candidate.key === key); if (!key || !line?.item?.is_serialized || line.pieces.some((piece) => piece.serial_number === serial)) return; updateLine(key, { pieces: [...line.pieces, newPiece(serial, defaultLocationId)] }); setUnassigned((old) => old.filter((value) => value !== serial)); };
  // Un seriale svuotato o duplicato a mano non deve poter arrivare al registro:
  // il backend lo rifiuterebbe comunque, ma con un errore a operazione avviata
  // invece che con un campo rosso mentre lo si scrive.
  const serialiSani = (line: ReceiveLine) => line.pieces.length > 0
    && line.pieces.every((piece) => normalizeSerial(piece.serial_number) !== '')
    && new Set(line.pieces.map((piece) => normalizeSerial(piece.serial_number))).size === line.pieces.length;
  // Un pulsante spento che non dice cosa manca è un vicolo cieco: si guarda lo
  // schermo cercando l'errore. Le condizioni sono le stesse di `valid`, dette
  // una per una, così si legge cosa resta da fare invece di indovinarlo.
  const mancante: string[] = [];
  if (!noteMode) mancante.push('Scegli una bolla, creane una nuova, oppure indica che la merce arriva senza bolla.');
  if (!defaultLocationId) mancante.push('Scegli l\'ubicazione predefinita nella sezione 2.');
  if (noteMode === 'new') {
    if (!noteDraft.number) mancante.push('Manca il numero della bolla.');
    if (!noteDraft.note_date) mancante.push('Manca la data della bolla.');
    if (!noteDraft.supplier_id) mancante.push('Manca il fornitore della bolla: sceglilo, oppure creane uno nuovo dallo stesso menù.');
  }
  lines.forEach((line, index) => {
    const dove = `Riga ${index + 1}${line.item ? ` (${line.item.part_number})` : ''}`;
    if (!line.item) { mancante.push(`${dove}: scegli il modello.`); return; }
    if (!(line.expected > 0)) mancante.push(`${dove}: i pezzi attesi devono essere almeno 1.`);
    if (line.item.is_serialized) {
      if (line.pieces.length === 0) mancante.push(`${dove}: acquisisci almeno un seriale, oppure rimuovi la riga.`);
      else if (line.pieces.some((piece) => normalizeSerial(piece.serial_number) === '')) mancante.push(`${dove}: c'è un seriale vuoto.`);
      else if (new Set(line.pieces.map((piece) => normalizeSerial(piece.serial_number))).size !== line.pieces.length) mancante.push(`${dove}: ci sono due seriali uguali.`);
    } else if (!(line.quantity > 0)) {
      mancante.push(`${dove}: i pezzi arrivati devono essere più di zero.`);
    }
  });

  const motivoAvanti = passo === 1
    ? (!noteMode ? 'Scegli una bolla, creane una nuova, oppure indica che la merce arriva senza bolla.'
      : noteMode === 'new' && !(noteDraft.number && noteDraft.note_date && noteDraft.supplier_id) ? 'Completa numero, data e fornitore della bolla.' : '')
    : passo === 2 ? (!defaultLocationId ? 'Scegli l\'ubicazione: è lì che finiranno i pezzi.' : '')
    : '';
  const puoAvanzare = motivoAvanti === '';
  // Su telefono i passi precedenti non sono più a schermo: prima di registrare
  // va rimesso davanti agli occhi cosa si sta per scrivere in magazzino.
  const riepilogo = <section className="space-y-3 rounded-xl border bg-white p-4">
    <h2 className="text-lg font-semibold">4. Conferma</h2><p className="text-sm text-slate-600">Questo è ciò che stai per registrare in magazzino.</p>
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
      <dt className="text-slate-500">Bolla</dt><dd>{noteMode === 'none' ? 'Senza bolla' : noteMode === 'new' ? `${noteDraft.number || '—'} · ${noteDraft.note_date}` : notes.find((note) => note.id === noteMode)?.number ?? '—'}</dd>
      <dt className="text-slate-500">Ubicazione</dt><dd>{locations.find((location) => location.id === defaultLocationId)?.code ?? '—'}</dd>
    </dl>
    <ul className="divide-y border-t text-sm">{lines.map((line, index) => { const arrivati = line.item?.is_serialized ? line.pieces.length : line.quantity; return <li key={line.key} className="flex items-center justify-between gap-3 py-2"><span className="min-w-0 truncate font-mono">{line.item?.part_number ?? `Riga ${index + 1}`}</span><span className={`shrink-0 tabular-nums ${arrivati === line.expected ? 'text-slate-700' : 'font-semibold text-amber-700'}`}>{arrivati} / {line.expected}</span></li>; })}</ul>
  </section>;
  const valid = Boolean(noteMode && defaultLocationId && lines.length && lines.every((line) => line.item && line.expected > 0 && (line.item.is_serialized ? serialiSani(line) : line.quantity > 0)) && (noteMode !== 'new' || (noteDraft.number && noteDraft.note_date && noteDraft.supplier_id)));
  const runReceive = async (action: () => Promise<{ created_unit_ids: string[]; movement_ids: string[] }>, pendingValue: PendingReceive) => { try { const response = await action(); onSuccess(response.created_unit_ids.length); setNoteMode(''); setLines([freshLine()]); setDefaultLocationId(''); setWarnings([]); setPending(null); setPasso(1); } catch (r) { if (r instanceof ApiError && r.status === 409 && r.code === 'CONFIRMATION_REQUIRED') { const found = Array.isArray(r.details.warnings) ? r.details.warnings as Warning[] : []; setWarnings(found); setPending(pendingValue); } else setError(messageOf(r)); } };
  const submit = async () => { if (!valid) return; setBusy(true); setError(''); setWarnings([]); setPending(null); try {
    if (noteMode === 'none') {
      // Niente `occurred_at`: la merce sta entrando adesso, e l'unico orologio
      // di cui questo sistema può rispondere è quello del server. Mandare
      // l'ora del browser significava che un PC avanti di pochi secondi
      // faceva fallire la registrazione con «La data di ricezione non può
      // essere nel futuro» — succedeva davvero, sulla ricezione senza bolla.
      const body: FreeReceiveRequest = { location_id: defaultLocationId, confirm_warnings: [], lines: lines.map((line) => ({ catalog_item_id: line.item!.id, condition: line.condition, ...(line.item!.is_serialized ? { serials: line.pieces.map((piece) => ({ serial_number: normalizeSerial(piece.serial_number), mac_address: piece.mac_address, location_id: piece.location_id === defaultLocationId ? undefined : piece.location_id })) } : { quantity: line.quantity }) })) };
      await runReceive(() => movementsApi.receive(body), { kind: 'free', body });
      return;
    }
    let noteId = noteMode; const ids = new Map<string, string>(); if (noteMode === 'new') { const note = await deliveryNotesApi.create({ ...noteDraft, po_number: noteDraft.po_number || null, lines: lines.map((line) => ({ catalog_item_id: line.item!.id, qty_expected: line.expected, condition: line.condition })) }); noteId = note.id; const complete = note.lines ? note : await deliveryNotesApi.get(note.id); (complete.lines ?? []).forEach((line, index) => { const source = lines[index]; if (source) ids.set(source.key, line.id); }); } else { for (const line of lines) { if (line.lineId) ids.set(line.key, line.lineId); else { const created = await deliveryNotesApi.addLine(noteId, { catalog_item_id: line.item!.id, qty_expected: line.expected, condition: line.condition }); ids.set(line.key, created.id); } } } if (ids.size !== lines.length) throw new Error('Impossibile associare tutte le righe della bolla.'); const body: ReceiveRequest = { location_id: defaultLocationId, confirm_warnings: [], lines: lines.map((line) => ({ line_id: ids.get(line.key)!, condition: line.condition, ...(line.item!.is_serialized ? { serials: line.pieces.map((piece) => ({ serial_number: normalizeSerial(piece.serial_number), mac_address: piece.mac_address, location_id: piece.location_id === defaultLocationId ? undefined : piece.location_id })) } : { quantity: line.quantity }) })) }; await runReceive(() => deliveryNotesApi.receive(noteId, body), { kind: 'note', noteId, body }); } catch (r) { setError(messageOf(r)); } finally { setBusy(false); } };
  const confirmWarnings = async () => { if (!pending) return; setBusy(true); setError(''); try { const confirmed = [...new Set(warnings.map((warning) => warning.code))]; if (pending.kind === 'free') await runReceive(() => movementsApi.receive({ ...pending.body, confirm_warnings: confirmed }), pending); else await runReceive(() => deliveryNotesApi.receive(pending.noteId, { ...pending.body, confirm_warnings: confirmed }), pending); } finally { setBusy(false); } };

  return <div className="space-y-6">{error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-red-800">{error}</p>}
    {stretto && <nav aria-label="Passi della ricezione" className="sticky top-16 z-20 rounded-xl border bg-white px-3 py-2 shadow-sm"><ol className="flex items-center gap-2">{PASSI.map((nome, indice) => { const numero = indice + 1; const fatto = numero < passo; return <li key={nome} className="flex min-w-0 flex-1 items-center gap-2 last:flex-none"><button type="button" disabled={numero > passo} aria-current={numero === passo ? 'step' : undefined} aria-label={`Passo ${numero}: ${nome}`} onClick={() => setPasso(numero)} className={`flex size-8 shrink-0 items-center justify-center rounded-full text-sm font-bold ${numero === passo ? 'bg-blue-600 text-white' : fatto ? 'bg-blue-100 text-blue-800' : 'bg-slate-100 text-slate-400'}`}>{fatto ? <Check size={16}/> : numero}</button>{numero < PASSI.length && <span aria-hidden className={`h-0.5 min-w-2 flex-1 ${fatto ? 'bg-blue-300' : 'bg-slate-200'}`}/>}</li>; })}</ol></nav>}
    {vedi(1) && <>
    <section className="space-y-4 rounded-xl border bg-white p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">1. Bolla</h2><p className="text-sm text-slate-600">Carica la bolla — foto, scansione o PDF, anche più pagine insieme — per precompilare una proposta, oppure procedi manualmente.</p></div><label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700">{scanningNote ? <Loader2 size={19} className="animate-spin" aria-hidden/> : <ScanLine size={19}/>}{scanningNote ? 'Lettura…' : 'Leggi bolla'}<input className="sr-only" type="file" accept={EXTRACTION_FILE_ACCEPT} capture="environment" multiple disabled={scanningNote} onChange={(e) => void readDeliveryNote(e.target.files)}/></label></div><Select label="Bolla" value={noteMode} onChange={(e) => void chooseNote(e.target.value)}><option value="">Seleziona una bolla aperta…</option>{notes.map((note) => <option key={note.id} value={note.id}>{note.number} · {note.note_date}</option>)}<option value="new">+ Nuova bolla</option><option value="none">Senza bolla (aggiungi il numero dopo)</option></Select>{noteMode === 'new' && <div className="grid gap-3 md:grid-cols-2"><Input label="Numero bolla" required value={noteDraft.number} onChange={(e) => setNoteDraft({ ...noteDraft, number: e.target.value })}/><Input label="Data" type="date" required value={noteDraft.note_date} onChange={(e) => setNoteDraft({ ...noteDraft, note_date: e.target.value })}/><Select label="Fornitore" required value={noteDraft.supplier_id} onChange={(e) => e.target.value === '__new' ? setShowSupplier(true) : setNoteDraft({ ...noteDraft, supplier_id: e.target.value })}><option value="">Seleziona…</option>{suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}<option value="__new">+ Nuovo fornitore</option></Select><Input label="Numero ordine (opzionale)" value={noteDraft.po_number} onChange={(e) => setNoteDraft({ ...noteDraft, po_number: e.target.value })}/></div>}{noteMode === 'none' && <p className="rounded-lg bg-blue-50 p-3 text-sm text-blue-800">La merce viene registrata subito in giacenza. Potrai collegare il numero di bolla in un secondo momento dal dettaglio di ogni pezzo, quando sarà disponibile.</p>}{noteExtraction && <p className="rounded-lg bg-green-50 p-3 text-sm text-green-800">Proposta caricata: {noteExtraction.lines.length} righe · motore {noteExtraction.engine} ({noteExtraction.duration_ms} ms). Controlla e modifica tutto prima di registrare.</p>}</section>
    {/* Fra il caricamento e la prima risposta passano parecchi secondi: è
        l'OCR di ogni pagina. Senza un segnale qui, l'unica cosa che cambia è
        la scritta sul pulsante, e sembra che la pagina si sia piantata. */}
    {scanningNote && <Busy title="Lettura della bolla in corso…">Sto elaborando le pagine caricate. Una foto richiede più tempo di un PDF, e ogni pagina in più si somma. Non ricaricare la pagina.</Busy>}
    <DeliveryNoteProposal analysis={analysis} onApply={(chosen) => void applyProposal(chosen)} onCreateItem={setItemFromProposal}/>
    </>}
    {noteMode && <>{vedi(2) && <section className="space-y-3 rounded-xl border bg-white p-4"><h2 className="text-lg font-semibold">2. Ubicazione predefinita</h2><Combobox label="Ubicazione" placeholder="Cerca per codice o nome…" query={locationQuery} onQueryChange={setLocationQuery} loading={locationSearching} options={locationOptions.map((location) => ({ id: location.id, label: `${location.code} · ${location.name}` }))} selectedLabel={locations.find((location) => location.id === defaultLocationId) ? `${locations.find((location) => location.id === defaultLocationId)!.code} · ${locations.find((location) => location.id === defaultLocationId)!.name}` : undefined} extraOption={{ id: '__new', label: '+ Nuova ubicazione' }} onSelect={(id) => id === '__new' ? setShowLocation(true) : chooseDefaultLocation(id)} hint="Vale per i prossimi pezzi; quelli già acquisiti conservano la propria ubicazione."/></section>}
    {vedi(3) && <>
    {proposalNotices.length > 0 && <section role="alert" className="space-y-2 rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-900"><div className="flex flex-wrap items-start justify-between gap-3"><h2 className="font-semibold">Da sapere sulle righe applicate</h2><Button type="button" variant="ghost" onClick={() => setProposalNotices([])}>Ho capito</Button></div><ul className="list-disc pl-5 text-sm">{proposalNotices.map((notice) => <li key={notice}>{notice}</li>)}</ul></section>}
    <section className="space-y-5"><div className="flex items-center justify-between"><h2 className="text-lg font-semibold">3. Righe e acquisizione</h2><Button type="button" variant="secondary" onClick={() => setLines((old) => [...old, freshLine()])}>+ Aggiungi riga</Button></div>
      <LabelCapture templates={templates} addedSignal={labelAdded}
        catalogQuery={catalogQuery} onCatalogQuery={setCatalogQuery} catalogOptions={catalogOptions} catalogSearching={catalogSearching}
        disabled={!defaultLocationId}
        disabledReason={!defaultLocationId ? 'Scegli prima l\'ubicazione predefinita nella sezione 2: è lì che finiranno i pezzi.' : undefined}
        onAdd={async (reading) => reading.item ? addFromLabel(reading, reading.item.id) : { ok: false as const, motivo: 'Il modello letto non è a catalogo: crealo prima.' }}
        onCreateItem={setLabelReading}/>{lines.map((line, index) => <ReceiveLineCard key={line.key} line={line} index={index} removable={!line.lineId && lines.length > 1} onRemove={() => setLines((old) => old.filter((v) => v.key !== line.key))} onChange={(change) => updateLine(line.key, change)} onSelectItem={(id) => selectItem(line.key, id)} catalogQuery={catalogQuery} onCatalogQuery={setCatalogQuery} catalogOptions={catalogOptions} catalogSearching={catalogSearching} locations={locations} defaultLocationId={defaultLocationId} templates={templates} onExtract={(result) => void recognizeItem(line.key, result)} onApplyExtracted={(values) => addExtracted(line.key, values)}/>)}</section>{unassigned.length > 0 && <section className="space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold">Seriali letti ma non assegnati</h2><p className="text-sm">{serializedLines.length > 0 ? 'Assegna ogni seriale a una riga oppure scartalo esplicitamente dalla proposta.' : 'Non c’è ancora nessuna riga con un articolo serializzato a cui assegnarli.'}</p></div><Button type="button" variant="ghost" onClick={() => setUnassigned([])}>Scarta tutti</Button></div>
      {/* Senza righe serializzate ogni tendina sarebbe vuota e ogni pulsante
          "Assegna" un vicolo cieco: meglio dire cosa manca e mostrare i seriali
          in forma compatta, invece di una lista di comandi che non fanno nulla. */}
      {serializedLines.length === 0
        ? <div className="space-y-2 rounded-lg border bg-white p-3"><p className="text-sm">Aggiungi qui sotto una riga scegliendo il modello a catalogo: appena c’è, potrai assegnarli. Se il modello non esiste ancora, crealo dalla riga con <strong>+ Nuovo articolo</strong>.</p><p className="break-all font-mono text-sm text-slate-700">{unassigned.join(' · ')}</p></div>
        : unassigned.map((serial) => <div key={serial} className="grid items-end gap-2 rounded-lg border bg-white p-2 sm:grid-cols-[1fr_2fr_auto_auto]"><p className="pb-3 font-mono font-medium">{serial}</p><Select label="Riga serializzata" value={serialTarget[serial] ?? ''} onChange={(e) => setSerialTarget((old) => ({ ...old, [serial]: e.target.value }))}><option value="">Seleziona…</option>{serializedLines.map(({ line, index }) => <option key={line.key} value={line.key}>Riga {index + 1} · {line.item?.part_number}</option>)}</Select><Button type="button" disabled={!serialTarget[serial]} onClick={() => assignUnassigned(serial)}>Assegna</Button><Button type="button" variant="ghost" onClick={() => setUnassigned((old) => old.filter((value) => value !== serial))}>Scarta</Button></div>)}</section>}</>}</>}
    {vedi(4) && <>
    {stretto && riepilogo}
    {warnings.length > 0 && <section className="space-y-3 rounded-xl border border-amber-400 bg-amber-50 p-4"><h2 className="font-semibold">Conferma richiesta</h2><p className="text-sm">Controlla gli avvisi: la ricezione non è ancora registrata.</p><ul className="list-disc pl-5">{warnings.map((warning, i) => <li key={`${warning.code}-${i}`}>{warning.message}{warning.serial_number ? ` (${warning.serial_number})` : ''}</li>)}</ul><Button type="button" loading={busy} onClick={() => void confirmWarnings()}>Conferma avvisi e registra</Button></section>}<div className="space-y-3">{!valid && mancante.length > 0 && <section className="rounded-xl border border-slate-300 bg-slate-50 p-4"><h2 className="font-semibold">Manca ancora qualcosa per registrare</h2><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-700">{mancante.map((voce) => <li key={voce}>{voce}</li>)}</ul></section>}{!stretto && <Button type="button" loading={busy} disabled={!valid || warnings.length > 0} onClick={() => void submit()}>Registra ricezione</Button>}</div>
    </>}
    {/* Su telefono l'azione principale non sta in fondo a una pagina lunga
        quanto tre schermate: sta qui, sempre a portata di pollice, e dice
        cosa manca invece di limitarsi a essere spenta. */}
    {stretto && <div className="sticky bottom-0 z-20 -mb-4 space-y-2 border-t bg-white/95 py-3 backdrop-blur">
      {!puoAvanzare && motivoAvanti && <p className="text-sm text-slate-600">{motivoAvanti}</p>}
      <div className="flex gap-2">
        <Button type="button" variant="secondary" disabled={passo === 1} onClick={() => setPasso((numero) => numero - 1)}><ChevronLeft size={18}/>Indietro</Button>
        {passo < PASSI.length
          ? <Button type="button" className="flex-1" disabled={!puoAvanzare} onClick={() => setPasso((numero) => numero + 1)}>Avanti<ChevronRight size={18}/></Button>
          : <Button type="button" className="flex-1" loading={busy} disabled={!valid || warnings.length > 0} onClick={() => void submit()}>Registra ricezione</Button>}
      </div>
    </div>}
    <Modal open={showSupplier} title="Nuovo fornitore" onClose={() => setShowSupplier(false)}><div className="space-y-4"><Input label="Nome" autoFocus value={supplierName} onChange={(e) => setSupplierName(e.target.value)}/><Button type="button" loading={busy} onClick={() => void createSupplier()}>Crea e seleziona</Button></div></Modal>
    <CatalogItemModal open={itemForLine !== null} onClose={() => setItemForLine(null)} onCreated={(item) => { setCatalog((old) => merge(old, [item])); if (itemForLine) updateLine(itemForLine, { item }); }}/>
    <CatalogItemModal open={labelReading !== null} prefill={labelReading ? { part_number: labelReading.part_number || undefined, is_serialized: true } : null} onClose={() => setLabelReading(null)} onCreated={(item) => { const reading = labelReading; setLabelReading(null); if (reading) void addFromLabel(reading, item.id).then((esito) => { if (esito.ok) setLabelAdded((n) => n + 1); else setError(esito.motivo); }); }}/>
    <CatalogItemModal open={itemFromProposal !== null} prefill={itemFromProposal ? { part_number: itemFromProposal.part_number ?? undefined, name: itemFromProposal.description || undefined, is_serialized: itemFromProposal.serials.length > 0 } : null} onClose={() => setItemFromProposal(null)} onCreated={(item) => { setCatalog((old) => merge(old, [item])); setAnalysis((old) => old ? { ...old, lines: old.lines.map((line) => line === itemFromProposal ? { ...line, catalog_item: { id: item.id, part_number: item.part_number, name: item.name, vendor_code: '' }, is_serialized: item.is_serialized } : line) } : old); setItemFromProposal(null); }}/>
    <Modal open={showLocation} title="Nuova ubicazione" onClose={() => setShowLocation(false)}><div className="grid gap-3 md:grid-cols-2"><Input label="Nome" autoFocus value={locationDraft.name} onChange={(e) => setLocationDraft({ ...locationDraft, name: e.target.value })} hint="Il codice lo ricava il sistema dal nome."/><Select label="Tipo" value={locationDraft.type} onChange={(e) => setLocationDraft({ ...locationDraft, type: e.target.value as LocationType })}>{locationTypes.map((type) => <option key={type}>{type}</option>)}</Select><Button type="button" loading={busy} onClick={() => void createLocation()}>Crea e seleziona</Button></div></Modal>
  </div>;
}
