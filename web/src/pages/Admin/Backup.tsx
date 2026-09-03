import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Database, Download, HardDriveDownload, RotateCcw } from "lucide-react";
import { maintenanceApi } from "../../api";
import { Button, Input, Modal, Table, useToast } from "../../components/ui";
import { formatDateTime } from "../../lib/format";
import { ErrorMessage, Loading } from "../common";

/** Byte in una misura che si legge: 4 GB, non 4294967296. */
const peso = (byte: number): string => {
  const unita = ["B", "kB", "MB", "GB", "TB"];
  let valore = byte;
  let indice = 0;
  while (valore >= 1024 && indice < unita.length - 1) { valore /= 1024; indice += 1; }
  return `${valore.toFixed(valore < 10 && indice > 0 ? 1 : 0)} ${unita[indice]}`;
};

const CONFERMA = "RIPRISTINA";

/** Copia di sicurezza e ripristino, con i numeri per decidere.
 *
 * La copia fatta da qui **non** resta sul server: arriva sul computer di chi
 * preme il pulsante. È voluto, ed è la parte che conta — una copia in più
 * sullo stesso disco del database non protegge da un disco che muore. Le
 * copie del server restano quelle del timer notturno, elencate qui sotto per
 * sapere che ci sono e quanto pesano.
 */
export function BackupAdmin() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const stato = useQuery({ queryKey: ["backup-status"], queryFn: maintenanceApi.status });
  const [scaricando, setScaricando] = useState(false);
  const [ripristino, setRipristino] = useState(false);
  const [conferma, setConferma] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [inCorso, setInCorso] = useState(false);
  const [esito, setEsito] = useState<string>("");
  const fileRef = useRef<HTMLInputElement>(null);

  const scarica = async () => {
    setScaricando(true);
    try {
      const blob = await maintenanceApi.backup();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `netstock-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "")}.dump`;
      anchor.style.display = "none";
      document.body.appendChild(anchor);
      anchor.click();
      window.setTimeout(() => { anchor.remove(); URL.revokeObjectURL(url); }, 0);
      toast.show("Copia creata e scaricata. Conservala fuori da questa macchina.", "success");
      await queryClient.invalidateQueries({ queryKey: ["backup-status"] });
    } catch { toast.show("Non è stato possibile creare la copia.", "error"); }
    finally { setScaricando(false); }
  };

  const esegui = async () => {
    if (!file || conferma.trim().toUpperCase() !== CONFERMA) return;
    setInCorso(true); setEsito("");
    try {
      const risposta = await maintenanceApi.restore(file, conferma.trim());
      if (risposta.ok) {
        toast.show(risposta.messaggio, "success");
        setRipristino(false); setFile(null); setConferma("");
        if (fileRef.current) fileRef.current.value = "";
        await queryClient.invalidateQueries();
      } else {
        setEsito(`${risposta.messaggio}${risposta.stato_precedente_ripristinato
          ? " Lo stato di prima è stato rimesso: il magazzino è come prima del tentativo."
          : " ATTENZIONE: lo stato di prima non è stato rimesso."} ${risposta.dettaglio}`);
      }
    } catch (motivo) { setEsito(motivo instanceof Error ? motivo.message : "Ripristino non riuscito."); }
    finally { setInCorso(false); }
  };

  if (stato.isLoading) return <Loading />;
  if (stato.isError || !stato.data) return <ErrorMessage />;
  const dati = stato.data;

  return (
    <div className="space-y-6">
      <section className="space-y-4 rounded-xl border bg-white p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold"><Database size={19} aria-hidden/>Copia di sicurezza</h2>
            <p className="text-sm text-slate-600">La copia viene creata adesso e scaricata sul tuo computer. Non resta sul server: una copia in più sullo stesso disco non protegge dal disco che si rompe.</p>
          </div>
          <Button loading={scaricando} onClick={() => void scarica()}><Download size={17}/>Scarica una copia adesso</Button>
        </div>
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div><dt className="text-sm text-slate-500">Database</dt><dd className="font-medium">{dati.database} · {peso(dati.byte_database)}</dd></div>
          <div><dt className="text-sm text-slate-500">PostgreSQL</dt><dd className="font-medium">{dati.versione_postgres}</dd></div>
          <div><dt className="text-sm text-slate-500">Revisione schema</dt><dd className="font-mono font-medium">{dati.revisione_schema ?? "—"}</dd></div>
          <div><dt className="text-sm text-slate-500">Strumenti</dt><dd className="font-medium">{dati.versione_strumenti}</dd></div>
        </dl>
        {dati.disco && (
          <p className="text-sm text-slate-600">Disco delle copie: {peso(dati.disco.libero)} liberi su {peso(dati.disco.totale)}.</p>
        )}
      </section>

      <section className="space-y-3 rounded-xl border bg-white p-5">
        <h2 className="font-semibold">Cosa contiene il database</h2>
        <Table
          rows={dati.tabelle.slice(0, 12)}
          keyOf={(riga) => riga.nome}
          empty="Nessuna tabella."
          columns={[
            { key: "nome", label: "Tabella", render: (riga) => <span className="font-mono text-sm">{riga.nome}</span> },
            { key: "byte", label: "Spazio", render: (riga) => peso(riga.byte) },
            // Stima del pianificatore: contare davvero ogni tabella a ogni
            // apertura costerebbe una scansione completa per un numero che
            // serve a farsi un'idea.
            { key: "righe", label: "Righe (stima)", render: (riga) => riga.righe_stimate.toLocaleString("it-IT") },
          ]}
        />
      </section>

      <section className="space-y-3 rounded-xl border bg-white p-5">
        <h2 className="font-semibold">Copie sul server</h2>
        <p className="text-sm text-slate-600">
          Le fa il timer notturno delle 02:30 in <span className="font-mono">/var/backups/netstock</span>. In tutto {peso(dati.byte_copie)}.
        </p>
        <Table
          rows={dati.copie_sul_server.slice(0, 10)}
          keyOf={(riga) => riga.nome}
          empty="Nessuna copia sul server: il backup automatico non è installato (make backup-timer)."
          columns={[
            { key: "nome", label: "File", render: (riga) => <span className="font-mono text-sm">{riga.nome}</span> },
            { key: "gruppo", label: "Tipo", render: (riga) => riga.gruppo },
            { key: "byte", label: "Peso", render: (riga) => peso(riga.byte) },
            { key: "quando", label: "Quando", render: (riga) => formatDateTime(new Date(riga.quando * 1000).toISOString()) },
          ]}
        />
      </section>

      <section className="space-y-3 rounded-xl border border-red-200 bg-red-50 p-5">
        <h2 className="flex items-center gap-2 font-semibold text-red-900"><RotateCcw size={19} aria-hidden/>Ripristino</h2>
        <p className="text-sm text-red-900">
          Riporta il database al contenuto di una copia. È l'unica operazione di questo sistema che <strong>cancella dei dati</strong>: tutto quello registrato dopo quella copia sparisce, movimenti compresi.
        </p>
        <p className="text-sm text-red-900">Prima di procedere viene salvato lo stato attuale, e se il ripristino fallisce viene rimesso. Falla quando non sta lavorando nessuno: durante l'operazione le tabelle vengono ricreate.</p>
        <Button variant="danger" onClick={() => { setRipristino(true); setEsito(""); }}><HardDriveDownload size={17}/>Ripristina da una copia…</Button>
      </section>

      <Modal open={ripristino} title="Ripristina da una copia" onClose={() => !inCorso && setRipristino(false)}>
        <div className="space-y-3">
          {esito && <p role="alert" className="whitespace-pre-wrap rounded-lg bg-red-50 p-3 text-sm text-red-800">{esito}</p>}
          <label className="block text-sm font-medium text-slate-700">File della copia (.dump)
            <input ref={fileRef} type="file" accept=".dump" className="mt-1 block w-full text-sm" onChange={(evento) => setFile(evento.target.files?.[0] ?? null)}/>
          </label>
          {file && <p className="text-sm text-slate-600">{file.name} · {peso(file.size)}</p>}
          <Input label={`Scrivi ${CONFERMA} per confermare`} value={conferma} onChange={(evento) => setConferma(evento.target.value)} autoComplete="off"/>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" disabled={inCorso} onClick={() => setRipristino(false)}>Annulla</Button>
            <Button variant="danger" loading={inCorso} disabled={!file || conferma.trim().toUpperCase() !== CONFERMA} onClick={() => void esegui()}>Ripristina adesso</Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
