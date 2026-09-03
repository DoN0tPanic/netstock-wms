import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Cpu, Terminal } from "lucide-react";
import { aiApi } from "../../api";
import { Badge, Button, Select, Table, useToast } from "../../components/ui";
import { ErrorMessage, Loading } from "../common";

const peso = (byte: number): string => `${(byte / 1e9).toFixed(1)} GB`;

/** Il modello che legge i documenti: quale è, quanto costa, come cambiarlo.
 *
 * Si sceglie **fra quelli installati**, non si scrive a mano: un nome vale
 * solo se Ollama ce l'ha scaricato — sono gigabyte — e un campo libero
 * permetterebbe di salvare qualcosa di plausibile e scoprire alla prima bolla
 * che non c'è.
 *
 * I tempi delle letture vere stanno qui accanto perché sono la risposta alla
 * domanda che porta su questa pagina: non «quale modello è più bravo», ma
 * «quanto ci mette sul ferro che ho».
 */
export function ModelliAdmin() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const stato = useQuery({ queryKey: ["ai-stato"], queryFn: aiApi.status });
  const [scelto, setScelto] = useState("");
  const [salvando, setSalvando] = useState(false);

  // L'elenco a discesa parte da quello in uso: aprirlo su una voce a caso
  // farebbe sembrare che il modello sia già cambiato.
  useEffect(() => { if (stato.data) setScelto(stato.data.modello_in_uso); }, [stato.data]);

  const salva = async () => {
    setSalvando(true);
    try {
      const aggiornato = await aiApi.setModel(scelto);
      toast.show(`Adesso legge con ${aggiornato.modello_in_uso}.`, "success");
      await queryClient.invalidateQueries({ queryKey: ["ai-stato"] });
    } catch (motivo) { toast.show(motivo instanceof Error ? motivo.message : "Non riesco a cambiare modello.", "error"); }
    finally { setSalvando(false); }
  };

  if (stato.isLoading) return <Loading/>;
  if (stato.isError || !stato.data) return <ErrorMessage/>;
  const dati = stato.data;

  return (
    <section className="space-y-4 rounded-xl border bg-white p-5">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-semibold"><Cpu size={19} aria-hidden/>Lettura automatica dei documenti</h2>
        <p className="text-sm text-slate-600">
          Quale modello legge bolle ed etichette. Si cambia da qui e vale dalla lettura successiva, senza riavviare niente.
        </p>
      </div>

      {!dati.attiva && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">La lettura automatica è spenta in configurazione (<span className="font-mono">EXTRACT_ENABLED=false</span>): il gestionale funziona identico, senza proposte.</p>}
      {!dati.ollama_raggiungibile && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">Ollama non risponde su <span className="font-mono">{dati.indirizzo_ollama}</span>: finché è così non posso né elencare né cambiare i modelli.</p>}

      {dati.ollama_raggiungibile && <>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-64 flex-1">
            <Select label="Modello in uso" value={scelto} onChange={(evento) => setScelto(evento.target.value)}>
              {dati.modelli.map((modello) => (
                <option key={modello.nome} value={modello.nome}>
                  {modello.nome} · {peso(modello.byte)}{modello.parametri ? ` · ${modello.parametri}` : ""}
                </option>
              ))}
            </Select>
          </div>
          <Button className="mb-[1.375rem]" loading={salvando} disabled={scelto === dati.modello_in_uso} onClick={() => void salva()}>Usa questo</Button>
        </div>

        <Table
          rows={dati.modelli}
          keyOf={(riga) => riga.nome}
          empty="Nessun modello installato: scaricane uno qui sotto."
          columns={[
            { key: "nome", label: "Modello", render: (riga) => <span className="font-mono text-sm">{riga.nome}</span> },
            { key: "peso", label: "Spazio", render: (riga) => peso(riga.byte) },
            { key: "par", label: "Parametri", render: (riga) => riga.parametri ?? "—" },
            { key: "quant", label: "Quantizzazione", render: (riga) => riga.quantizzazione ?? "—" },
            { key: "stato", label: "", render: (riga) => <div className="flex gap-2">
              {riga.nome === dati.modello_in_uso && <Badge tone="success">in uso</Badge>}
              {riga.in_memoria && <Badge tone="info">caricato</Badge>}
            </div> },
          ]}
        />

        {/* Nessun pulsante per scaricare, ed è una scelta: il servizio che
            legge i documenti non ha una via d'uscita verso internet (§7.5), e
            dargliela per comodità annullerebbe una misura dichiarata. Lo
            scaricamento lo fa un container usa e getta, con un comando. */}
        <div className="space-y-2 rounded-lg bg-slate-50 p-4">
          <h3 className="flex items-center gap-2 font-semibold"><Terminal size={17} aria-hidden/>Aggiungere un modello</h3>
          <p className="text-sm text-slate-600">
            Sulla macchina che ospita NetStock, una riga:
          </p>
          <pre className="overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">make ollama-pull MODEL=qwen3:8b</pre>
          <p className="text-sm text-slate-600">
            Non c'è un pulsante qui perché il servizio che legge i documenti non ha una via d'uscita verso
            internet, per scelta: è la misura che garantisce che il testo di una bolla non possa uscire dalla
            macchina. Lo scaricamento lo fa un container temporaneo che poi sparisce, e il modello nuovo
            compare in questo elenco al riavvio del servizio.
          </p>
        </div>
      </>}

      {dati.tempi.length > 0 && (
        <div className="space-y-2">
          <h3 className="font-semibold">Quanto ci mette, su questa macchina</h3>
          {/* È il numero che risponde davvero alla domanda «conviene
              cambiare»: non quanto è bravo il modello in astratto, ma quanti
              secondi costa una bolla sul ferro che c'è. */}
          <Table
            rows={dati.tempi}
            keyOf={(riga) => riga.engine}
            empty=""
            columns={[
              { key: "motore", label: "Motore", render: (riga) => <span className="font-mono text-sm">{riga.engine}</span> },
              { key: "letture", label: "Letture (90 gg)", render: (riga) => riga.letture },
              { key: "medi", label: "Secondi medi", render: (riga) => riga.secondi_medi },
              { key: "max", label: "Peggiore", render: (riga) => `${riga.secondi_massimo}s` },
              { key: "usate", label: "Usate davvero", render: (riga) => riga.usate },
            ]}
          />
        </div>
      )}
    </section>
  );
}
