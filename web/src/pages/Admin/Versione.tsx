import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import type { ReactNode } from "react";
import { versioneApi } from "../../api";
import { formatDateTime } from "../../lib/format";
import { ErrorMessage, Loading } from "../common";

/** Da quale commit viene l'interfaccia aperta in questo browser. */
const commitInterfaccia = (): string | null => import.meta.env.VITE_COMMIT || null;

const Voce = ({ titolo, children }: { titolo: string; children: ReactNode }) => (
  <div><dt className="text-sm text-slate-500">{titolo}</dt><dd className="font-medium">{children}</dd></div>
);

const Avviso = ({ children }: { children: ReactNode }) => (
  <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{children}</p>
);

// Serve a una domanda precisa: produzione e sviluppo girano lo stesso codice?
// Il commit risponde, lo schema dice se le migrazioni sono passate, l'ora di
// avvio se dopo un aggiornamento il servizio è davvero ripartito.
export function VersioneAdmin() {
  const stato = useQuery({ queryKey: ["versione"], queryFn: versioneApi.leggi });
  if (stato.isLoading) return <Loading />;
  if (stato.isError || !stato.data) return <ErrorMessage />;
  const dati = stato.data;
  const interfaccia = commitInterfaccia();
  const schemaAggiornato = dati.schema_attuale !== null && dati.schema_attuale === dati.schema_previsto;
  // Un browser può tenere aperta l'interfaccia di prima di un aggiornamento:
  // parla con il server nuovo, ma con le pagine vecchie.
  const interfacciaDiversa = Boolean(interfaccia && dati.commit && interfaccia !== dati.commit);
  return (
    <section className="space-y-4 rounded-xl border bg-white p-5" aria-labelledby="titolo-versione">
      <div>
        <h2 id="titolo-versione" className="flex items-center gap-2 text-lg font-semibold"><Info size={19} aria-hidden/>Versione</h2>
        <p className="text-sm text-slate-600">Da quale codice è costruita questa installazione. Per confrontare produzione e sviluppo basta il commit: lo stesso commit è lo stesso programma.</p>
      </div>
      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Voce titolo="Commit"><span className="font-mono">{dati.commit ?? "sconosciuto"}</span></Voce>
        <Voce titolo="Data del commit">{formatDateTime(dati.data_commit)}</Voce>
        <Voce titolo="Immagine costruita">{formatDateTime(dati.costruita)}</Voce>
        <Voce titolo="In esecuzione dal">{formatDateTime(dati.avviata)}</Voce>
        <Voce titolo="Schema del database">
          <span className="font-mono">{dati.schema_attuale ?? "—"}</span>{schemaAggiornato ? " · aggiornato" : ""}
        </Voce>
        <Voce titolo="Componenti">Python {dati.python} · PostgreSQL {dati.postgresql}</Voce>
      </dl>
      {!schemaAggiornato && (
        <Avviso>Lo schema del database è alla revisione <span className="font-mono">{dati.schema_attuale ?? "—"}</span>, ma questo codice si aspetta la <span className="font-mono">{dati.schema_previsto ?? "—"}</span>: le migrazioni non sono passate. Controlla i log del servizio api.</Avviso>
      )}
      {interfacciaDiversa && (
        <Avviso>L'interfaccia aperta in questo browser viene da un altro commit (<span className="font-mono">{interfaccia}</span>): ricarica la pagina per usare quella aggiornata.</Avviso>
      )}
      {dati.commit === null && (
        <p className="text-sm text-slate-500">Il commit non è disponibile: l'immagine non è stata costruita da una copia git del progetto.</p>
      )}
    </section>
  );
}
