import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Download, FileText, Folder, FolderOpen, Plus, RefreshCw, Search, Trash2, Upload } from "lucide-react";
import { documentsApi, suppliersApi } from "../api";
import type { ArchivedDocument, Supplier } from "../types/api";
import { useAuth } from "../hooks/useAuth";
import { can } from "../lib/permissions";
import { Badge, Button, Input, Modal, Select, Table, useToast } from "../components/ui";
import { formatDateTime } from "../lib/format";
import { ErrorMessage, Loading, Page } from "./common";

const peso = (byte: number): string => {
  const unita = ["B", "kB", "MB"];
  let valore = byte;
  let indice = 0;
  while (valore >= 1024 && indice < unita.length - 1) { valore /= 1024; indice += 1; }
  return `${valore.toFixed(valore < 10 && indice > 0 ? 1 : 0)} ${unita[indice]}`;
};

/** Come si è arrivati al fornitore, detto a chi guarda.
 *
 * Non è pignoleria: «partita IVA» vuol dire che si può non controllare,
 * «intestazione» vuol dire che è probabile e un'occhiata conviene. Un
 * riconoscimento senza il suo perché costringe a controllarli tutti o a
 * fidarsi di tutti.
 */
const riconoscimento: Record<string, { testo: string; tono: "success" | "info" | "neutral" }> = {
  piva: { testo: "partita IVA", tono: "success" },
  intestazione: { testo: "intestazione", tono: "info" },
  manuale: { testo: "assegnato a mano", tono: "neutral" },
};

const letturaEtichetta: Record<string, { testo: string; tono: "success" | "info" | "danger" }> = {
  testo: { testo: "testo del PDF", tono: "success" },
  ocr: { testo: "letto con OCR", tono: "info" },
  nessuno: { testo: "nessun testo", tono: "danger" },
};

/** Archivio delle bolle scansionate.
 *
 * È una sezione **stagna** per scelta: non compare nella ricerca globale e ha
 * la sua. La ricerca globale porta dritto a un pezzo in magazzino; qui si
 * cerca dentro documenti che citano qualunque cosa, comprese merci mai
 * registrate. Mescolarle vorrebbe dire che cercare un seriale restituisce
 * anche ogni bolla che lo nomina di sfuggita.
 */
function BottoneFornitore({ attivo, onClick, children }: { attivo: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={attivo}
      className={`inline-flex min-h-9 items-center gap-2 rounded-full border px-3 py-1.5 text-sm ${attivo ? "border-blue-600 bg-blue-50 font-semibold text-blue-800" : "border-slate-300 bg-white hover:bg-slate-50"}`}>
      {children}
    </button>
  );
}

export function Archivio() {
  const { session } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [cerca, setCerca] = useState("");
  const [ritardato, setRitardato] = useState("");
  const [caricando, setCaricando] = useState(false);
  const [testoDi, setTestoDi] = useState<{ nome: string; testo: string; metodo: string } | null>(null);
  const [daEliminare, setDaEliminare] = useState<ArchivedDocument | null>(null);
  // `null` = tutti; `"nessuno"` = quelli ancora da assegnare.
  const [fornitore, setFornitore] = useState<string | null>(null);
  const [riesaminando, setRiesaminando] = useState(false);
  const [nuovoFornitore, setNuovoFornitore] = useState<{ nome: string; piva: string } | null>(null);
  const [creando, setCreando] = useState(false);

  // La ricerca parte quando si smette di scrivere, non a ogni tasto: cercare
  // dentro il testo di tutti i documenti a ogni carattere è lavoro sprecato.
  useEffect(() => {
    const attesa = window.setTimeout(() => setRitardato(cerca.trim()), 300);
    return () => window.clearTimeout(attesa);
  }, [cerca]);

  const query = useQuery({
    queryKey: ["documenti", ritardato, fornitore],
    queryFn: () => documentsApi.list({
      q: ritardato,
      page_size: 50,
      supplier_id: fornitore && fornitore !== "nessuno" ? fornitore : undefined,
      senza_fornitore: fornitore === "nessuno" ? true : undefined,
    }),
  });
  // I conteggi non dipendono dalla ricerca né dalla pagina: sono l'indice
  // dell'archivio e devono restare fermi mentre si sfoglia.
  const conti = useQuery({ queryKey: ["documenti", "fornitori"], queryFn: () => documentsApi.fornitori() });
  const anagrafica = useQuery({ queryKey: ["suppliers", "archivio"], queryFn: () => suppliersApi.list() });

  const assegna = async (documento: ArchivedDocument, supplierId: string) => {
    try {
      await documentsApi.scegliFornitore(documento.id, supplierId || null);
      await queryClient.invalidateQueries({ queryKey: ["documenti"] });
    } catch (motivo) {
      toast.show(motivo instanceof Error ? motivo.message : "Non riesco a cambiare il fornitore.", "error");
    }
  };

  const creaFornitore = async () => {
    if (!nuovoFornitore?.nome.trim()) return;
    setCreando(true);
    try {
      const creato = await suppliersApi.create({
        name: nuovoFornitore.nome.trim(),
        vat_number: nuovoFornitore.piva.trim() || null,
      });
      setNuovoFornitore(null);
      // Un fornitore lo si crea guardando una bolla che non si sa dove
      // mettere: il passo successivo è sempre riconoscerla. Farlo da soli
      // evita di creare il fornitore e restare davanti alla stessa bolla
      // ancora da assegnare, chiedendosi cos'altro manchi. Tocca solo i
      // documenti mai riconosciuti, mai una decisione presa da una persona.
      const esito = await documentsApi.riesamina();
      toast.show(esito.assegnati
        ? `${creato.name} aggiunto, e ${esito.assegnati} ${esito.assegnati === 1 ? "bolla riconosciuta" : "bolle riconosciute"}.`
        : `${creato.name} aggiunto ai fornitori. Nessuna bolla da assegnare lo nomina: mettilo a mano dove serve.`,
        "success");
      await queryClient.invalidateQueries({ queryKey: ["suppliers"] });
      await queryClient.invalidateQueries({ queryKey: ["documenti"] });
    } catch (motivo) {
      toast.show(motivo instanceof Error ? motivo.message : "Fornitore non creato.", "error");
    } finally { setCreando(false); }
  };

  const riesamina = async () => {
    setRiesaminando(true);
    try {
      const esito = await documentsApi.riesamina();
      toast.show(esito.assegnati
        ? `${esito.assegnati} di ${esito.esaminati} documenti assegnati a un fornitore.`
        : `Nessuno dei ${esito.esaminati} documenti da assegnare corrisponde a un fornitore in anagrafica.`,
        esito.assegnati ? "success" : "info");
      await queryClient.invalidateQueries({ queryKey: ["documenti"] });
    } catch (motivo) {
      toast.show(motivo instanceof Error ? motivo.message : "Riesame non riuscito.", "error");
    } finally { setRiesaminando(false); }
  };

  const carica = async (file: File | undefined) => {
    if (!file) return;
    setCaricando(true);
    try {
      const documento = await documentsApi.upload(file);
      const come = letturaEtichetta[documento.extraction_method]?.testo ?? documento.extraction_method;
      toast.show(`${documento.filename} archiviato (${come}).`, "success");
      await queryClient.invalidateQueries({ queryKey: ["documenti"] });
    } catch (motivo) {
      toast.show(motivo instanceof Error ? motivo.message : "Caricamento non riuscito.", "error");
    } finally { setCaricando(false); }
  };

  const elimina = async () => {
    if (!daEliminare) return;
    try {
      await documentsApi.remove(daEliminare.id);
      toast.show(`${daEliminare.filename} tolto dall'archivio.`, "success");
      setDaEliminare(null);
      await queryClient.invalidateQueries({ queryKey: ["documenti"] });
    } catch (motivo) { toast.show(motivo instanceof Error ? motivo.message : "Eliminazione non riuscita.", "error"); }
  };

  const mostraTesto = async (documento: ArchivedDocument) => {
    try {
      const letto = await documentsApi.text(documento.id);
      setTestoDi({ nome: letto.filename, testo: letto.text, metodo: letto.extraction_method });
    } catch { toast.show("Non riesco a leggere il testo di questo documento.", "error"); }
  };
  // Raggruppa quello che è stato caricato: prima quelli senza fornitore, che
  // sono il lavoro da fare, poi i fornitori in ordine alfabetico. Il gruppo si
  // costruisce sui documenti in pagina — chi ne ha molti filtra col pulsante
  // del fornitore, che chiede al server solo i suoi.
  const gruppi = (() => {
    const per = new Map<string, { nome: string; righe: ArchivedDocument[] }>();
    for (const riga of query.data?.items ?? []) {
      const chiave = riga.supplier_id ?? "nessuno";
      if (!per.has(chiave)) per.set(chiave, { nome: riga.supplier_name ?? "Da assegnare", righe: [] });
      per.get(chiave)!.righe.push(riga);
    }
    const senza = per.get("nessuno");
    const altri = [...per.entries()].filter(([k]) => k !== "nessuno")
      .sort((a, b) => a[1].nome.localeCompare(b[1].nome, "it"));
    return [...(senza ? [["nessuno", senza] as const] : []), ...altri];
  })();

  return (
    <Page
      title="Archivio bolle"
      description="I PDF delle bolle scansionate, cercabili per quello che c'è scritto dentro"
      actions={can(session?.role, "operate") ? (
        <label className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 font-medium text-white hover:bg-blue-700">
          <Upload size={18} aria-hidden/>{caricando ? "Caricamento…" : "Carica un PDF"}
          <input className="sr-only" type="file" accept="application/pdf,.pdf" disabled={caricando}
            onChange={(evento) => { void carica(evento.target.files?.[0]); evento.target.value = ""; }}/>
        </label>
      ) : undefined}
    >
      {/* Ricerca propria, e lo dice: questa casella non è quella in cima alla
          pagina, e cerca in un posto diverso. */}
      <div className="rounded-xl border bg-white p-4">
        <Input aria-label="Cerca nell'archivio" value={cerca} onChange={(evento) => setCerca(evento.target.value)}
          placeholder="Numero d'ordine, cliente, qualsiasi cosa scritta nella bolla…"
          hint="Cerca dentro il contenuto dei PDF, non solo nel nome del file. Questa ricerca vale solo per l'archivio."/>
      </div>

      {conti.data && conti.data.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <BottoneFornitore attivo={fornitore === null} onClick={() => setFornitore(null)}>
            Tutti <span className="text-slate-500">{conti.data.reduce((somma, riga) => somma + riga.count, 0)}</span>
          </BottoneFornitore>
          {conti.data.some((riga) => !riga.supplier_id) && (
            <BottoneFornitore attivo={fornitore === "nessuno"} onClick={() => setFornitore("nessuno")}>
              Da assegnare <span className="text-slate-500">{conti.data.find((riga) => !riga.supplier_id)?.count}</span>
            </BottoneFornitore>
          )}
          {conti.data.filter((riga) => riga.supplier_id).map((riga) => (
            <BottoneFornitore key={riga.supplier_id} attivo={fornitore === riga.supplier_id}
              onClick={() => setFornitore(riga.supplier_id)}>
              {riga.supplier_name} <span className="text-slate-500">{riga.count}</span>
            </BottoneFornitore>
          ))}
          {can(session?.role, "operate") && <>
            {/* Il fornitore nuovo si crea da qui: è dove ci si accorge che
                manca — davanti a una bolla che non si sa dove mettere — e
                mandare in un'altra sezione vuol dire perdere il filo. */}
            <button type="button" onClick={() => setNuovoFornitore({ nome: "", piva: "" })}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-dashed border-slate-400 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50">
              <Plus size={15} aria-hidden/>Nuovo fornitore
            </button>
            {conti.data.some((riga) => !riga.supplier_id) && (
              <Button variant="ghost" className="ml-auto" loading={riesaminando} onClick={() => void riesamina()}>
                <RefreshCw size={16} aria-hidden/>Riconosci di nuovo
              </Button>
            )}
          </>}
        </div>
      )}

      {query.isLoading ? <Loading/> : query.isError || !query.data ? <ErrorMessage/> : (
        query.data.items.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-slate-600">
            {fornitore === "nessuno" && !ritardato
              ? "Ogni documento in archivio ha il suo fornitore."
              : ritardato
                ? <span>Nessun documento contiene «{ritardato}». Se sai che c'è, apri un documento e guarda «testo letto»: su una scansione storta l'OCR sbaglia qualche carattere.</span>
                : "L'archivio è vuoto. Carica il PDF di una bolla per ritrovarlo poi cercando quello che c'è scritto dentro."}
          </div>
        ) : <>
          <p className="text-sm text-slate-600" aria-live="polite">
            {query.data.total} {query.data.total === 1 ? "documento" : "documenti"}
            {ritardato && ` per «${ritardato}»`}
            {query.data.items.length < query.data.total && ` · ne vedi ${query.data.items.length}, filtra per fornitore o cerca per restringere`}
          </p>
          {gruppi.map(([chiave, gruppo]) => (
            <section key={chiave} className="space-y-3">
              <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
                {chiave === "nessuno" ? <FolderOpen size={16} aria-hidden/> : <Folder size={16} aria-hidden/>}
                {gruppo.nome}
                <span className="font-normal normal-case text-slate-400">{gruppo.righe.length}</span>
              </h2>
              <ul className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-4">
                {gruppo.righe.map((riga) => (
                  <Scheda key={riga.id} documento={riga} fornitori={anagrafica.data?.items ?? []}
                    puoOperare={can(session?.role, "operate")} puoEliminare={can(session?.role, "manage_users")}
                    onAssegna={(id) => void assegna(riga, id)}
                    onTesto={() => void mostraTesto(riga)}
                    onElimina={() => setDaEliminare(riga)}/>
                ))}
              </ul>
            </section>
          ))}
        </>
      )}

      <Modal open={nuovoFornitore !== null} title="Nuovo fornitore" onClose={() => setNuovoFornitore(null)}>
        <form className="space-y-4" onSubmit={(evento) => { evento.preventDefault(); void creaFornitore(); }}>
          <Input label="Ragione sociale" required autoFocus value={nuovoFornitore?.nome ?? ""}
            onChange={(evento) => setNuovoFornitore({ ...nuovoFornitore!, nome: evento.target.value })}/>
          <Input label="Partita IVA (facoltativa)" value={nuovoFornitore?.piva ?? ""}
            onChange={(evento) => setNuovoFornitore({ ...nuovoFornitore!, piva: evento.target.value })}
            hint="Se la metti, le bolle di questo fornitore si riconoscono da sole: undici cifre stampate sul documento non capitano per caso."/>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setNuovoFornitore(null)}>Annulla</Button>
            <Button type="submit" loading={creando} disabled={!nuovoFornitore?.nome.trim()}>Crea fornitore</Button>
          </div>
        </form>
      </Modal>

      <Modal open={testoDi !== null} title={`Testo letto da ${testoDi?.nome ?? ""}`} onClose={() => setTestoDi(null)}>
        <div className="space-y-3">
          <p className="text-sm text-slate-600">
            È su questo che cerca l'archivio. Se manca quello che stai cercando, il problema è la lettura del documento, non la ricerca
            {testoDi?.metodo === "ocr" && " — questo è stato letto con l'OCR, che su una scansione storta sbaglia qualche carattere"}.
          </p>
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-100 p-3 text-xs">{testoDi?.testo || "(nessun testo estratto)"}</pre>
        </div>
      </Modal>

      <Modal open={daEliminare !== null} title={`Elimina ${daEliminare?.filename ?? ""}`} onClose={() => setDaEliminare(null)}>
        <div className="space-y-3 text-sm">
          <p>Il documento viene tolto dall'archivio e il file cancellato. Se è la sola copia di quella bolla, non si recupera.</p>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setDaEliminare(null)}>Annulla</Button>
            <Button variant="danger" onClick={() => void elimina()}>Elimina</Button>
          </div>
        </div>
      </Modal>
    </Page>
  );
}

/** Un documento come scheda: prima la faccia, poi il nome.
 *
 * L'anteprima non è decorazione. Una bolla si riconosce dalla sua forma —
 * l'intestazione del fornitore, la tabella delle righe — molto prima che dal
 * nome, che è quasi sempre `scan_qualcosa.pdf`. L'immagine si carica pigra:
 * venti schede sono venti richieste, e non tutte finiscono a schermo.
 */
function Scheda({ documento, fornitori, puoOperare, puoEliminare, onAssegna, onTesto, onElimina }: {
  documento: ArchivedDocument;
  fornitori: Supplier[];
  puoOperare: boolean;
  puoEliminare: boolean;
  onAssegna: (supplierId: string) => void;
  onTesto: () => void;
  onElimina: () => void;
}) {
  const [senzaAnteprima, setSenzaAnteprima] = useState(false);
  const lettura = letturaEtichetta[documento.extraction_method];
  const come = documento.supplier_source ? riconoscimento[documento.supplier_source] : undefined;
  return (
    <li className="group flex flex-col overflow-hidden rounded-xl border bg-white transition hover:border-slate-300 hover:shadow-sm">
      <a className="relative block aspect-[3/4] overflow-hidden bg-slate-100"
        href={documentsApi.fileUrl(documento.id)} target="_blank" rel="noreferrer"
        title={`Apri ${documento.filename}`}>
        {senzaAnteprima ? (
          <span className="flex h-full items-center justify-center text-slate-400"><FileText size={40} aria-hidden/></span>
        ) : (
          <img src={documentsApi.anteprimaUrl(documento.id)} alt="" loading="lazy"
            className="h-full w-full object-cover object-top" onError={() => setSenzaAnteprima(true)}/>
        )}
        {lettura && (
          <span className="absolute bottom-1 left-1"><Badge tone={lettura.tono}>{lettura.testo}</Badge></span>
        )}
      </a>
      <div className="flex flex-1 flex-col gap-2 p-3">
        <p className="line-clamp-2 break-all text-sm font-medium" title={documento.filename}>{documento.filename}</p>
        <p className="text-xs text-slate-500">
          {peso(documento.byte_size)}{documento.pages ? ` · ${documento.pages} pag.` : ""}
          {documento.delivery_note_number && ` · bolla ${documento.delivery_note_number}`}
        </p>
        {puoOperare ? (
          <div className="space-y-1">
            <Select aria-label={`Fornitore di ${documento.filename}`} className="min-h-9 py-1 text-sm"
              value={documento.supplier_id ?? ""} onChange={(evento) => onAssegna(evento.target.value)}>
              <option value="">— da assegnare —</option>
              {fornitori.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
            </Select>
            {come && <Badge tone={come.tono}>{come.testo}</Badge>}
          </div>
        ) : come && <Badge tone={come.tono}>{come.testo}</Badge>}
        <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-sm">
          <a className="inline-flex items-center gap-1 text-slate-700 hover:underline"
            href={documentsApi.downloadUrl(documento.id)} download={documento.filename}>
            <Download size={15} aria-hidden/>Scarica
          </a>
          <button type="button" className="inline-flex items-center gap-1 text-slate-700 hover:underline" onClick={onTesto}>
            <Search size={15} aria-hidden/>Testo
          </button>
          {puoEliminare && (
            <button type="button" className="inline-flex items-center gap-1 text-red-700 hover:underline" onClick={onElimina}>
              <Trash2 size={15} aria-hidden/>Elimina
            </button>
          )}
        </div>
      </div>
    </li>
  );
}
