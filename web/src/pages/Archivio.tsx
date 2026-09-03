import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { FileText, Search, Trash2, Upload } from "lucide-react";
import { documentsApi } from "../api";
import type { ArchivedDocument } from "../types/api";
import { useAuth } from "../hooks/useAuth";
import { can } from "../lib/permissions";
import { Badge, Button, Input, Modal, Table, useToast } from "../components/ui";
import { formatDateTime } from "../lib/format";
import { ErrorMessage, Loading, Page } from "./common";

const peso = (byte: number): string => {
  const unita = ["B", "kB", "MB"];
  let valore = byte;
  let indice = 0;
  while (valore >= 1024 && indice < unita.length - 1) { valore /= 1024; indice += 1; }
  return `${valore.toFixed(valore < 10 && indice > 0 ? 1 : 0)} ${unita[indice]}`;
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
export function Archivio() {
  const { session } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [cerca, setCerca] = useState("");
  const [ritardato, setRitardato] = useState("");
  const [caricando, setCaricando] = useState(false);
  const [testoDi, setTestoDi] = useState<{ nome: string; testo: string; metodo: string } | null>(null);
  const [daEliminare, setDaEliminare] = useState<ArchivedDocument | null>(null);

  // La ricerca parte quando si smette di scrivere, non a ogni tasto: cercare
  // dentro il testo di tutti i documenti a ogni carattere è lavoro sprecato.
  useEffect(() => {
    const attesa = window.setTimeout(() => setRitardato(cerca.trim()), 300);
    return () => window.clearTimeout(attesa);
  }, [cerca]);

  const query = useQuery({
    queryKey: ["documenti", ritardato],
    queryFn: () => documentsApi.list({ q: ritardato, page_size: 50 }),
  });

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

      {query.isLoading ? <Loading/> : query.isError || !query.data ? <ErrorMessage/> : <>
        <p className="text-sm text-slate-600" aria-live="polite">
          {query.data.total} {query.data.total === 1 ? "documento" : "documenti"}
          {ritardato && ` per «${ritardato}»`}
        </p>
        <Table
          rows={query.data.items}
          keyOf={(riga) => riga.id}
          empty={ritardato
            ? <span>Nessun documento contiene «{ritardato}». Se sai che c'è, apri un documento e guarda «testo letto»: su una scansione storta l'OCR sbaglia qualche carattere.</span>
            : <span>L'archivio è vuoto. Carica il PDF di una bolla per ritrovarlo poi cercando quello che c'è scritto dentro.</span>}
          columns={[
            { key: "file", label: "Documento", render: (riga) => (
              <a className="inline-flex items-center gap-2 font-medium text-blue-700 underline" href={documentsApi.fileUrl(riga.id)} target="_blank" rel="noreferrer">
                <FileText size={16} aria-hidden/>{riga.filename}
              </a>
            ) },
            { key: "lettura", label: "Testo", render: (riga) => {
              const etichetta = letturaEtichetta[riga.extraction_method];
              return <Badge tone={etichetta?.tono ?? "neutral"}>{etichetta?.testo ?? riga.extraction_method}</Badge>;
            } },
            { key: "bolla", label: "Bolla", render: (riga) => riga.delivery_note_number ?? "—" },
            { key: "peso", label: "Peso", render: (riga) => `${peso(riga.byte_size)}${riga.pages ? ` · ${riga.pages} pag.` : ""}` },
            { key: "quando", label: "Caricato", render: (riga) => formatDateTime(riga.uploaded_at) },
            { key: "azioni", label: "", render: (riga) => (
              <div className="flex flex-wrap gap-2">
                <Button variant="ghost" onClick={() => void mostraTesto(riga)}><Search size={16}/>Testo letto</Button>
                {can(session?.role, "manage_users") && (
                  <Button variant="ghost" className="text-red-700" onClick={() => setDaEliminare(riga)}><Trash2 size={16}/>Elimina</Button>
                )}
              </div>
            ) },
          ]}
        />
      </>}

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
