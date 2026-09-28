import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, X } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { avvisiApi } from '../api';
import { useAuth } from '../hooks/useAuth';
import { avvisoOrologio } from '../lib/orologio';

const CHIAVE = 'netstock.avvisi.nascosti';
const UN_GIORNO = 24 * 3600_000;
type Nascosti = { codici: string[]; fino: number };

// La memoria del browser può mancare (finestra privata, dati bloccati): allora
// il riquadro si nasconde solo fino al prossimo caricamento.
const leggiNascosti = (): Nascosti | null => {
  try { return JSON.parse(localStorage.getItem(CHIAVE) ?? 'null') as Nascosti | null; } catch { return null; }
};

// Ogni avviso viene da un guaio già successo e passato inosservato: due notti
// di backup vuoti, il disco riempito dalla cache delle build, l'orologio della
// produzione avanti di due ore. Solo per gli amministratori: sono gli unici che
// possono farci qualcosa.
export function AvvisiProduzione() {
  const { session } = useAuth();
  const amministratore = Boolean(session?.permissions?.can_administer);
  const stato = useQuery({ queryKey: ['avvisi'], queryFn: avvisiApi.leggi, enabled: amministratore, refetchInterval: 10 * 60_000 });
  const [nascosti, setNascosti] = useState(leggiNascosti);
  if (!amministratore || !stato.data) return null;

  const orologio = avvisoOrologio(stato.data.ora_server, stato.dataUpdatedAt);
  const elenco = orologio ? [...stato.data.avvisi, orologio] : stato.data.avvisi;
  const codici = elenco.map((avviso) => avviso.codice).sort();
  // Nascosto per un giorno, ma solo quello che si è già visto: un problema
  // nuovo fa ricomparire il riquadro.
  const nascosto = nascosti !== null && nascosti.fino > Date.now() && codici.every((codice) => nascosti.codici.includes(codice));
  if (elenco.length === 0 || nascosto) return null;

  const nascondi = () => {
    const valore = { codici, fino: Date.now() + UN_GIORNO };
    try { localStorage.setItem(CHIAVE, JSON.stringify(valore)); } catch { /* vedi leggiNascosti */ }
    setNascosti(valore);
  };
  const critico = elenco.some((avviso) => avviso.gravita === 'critico');
  return (
    // Un avviso, non una sezione della pagina: niente titolo di sezione, che
    // passerebbe davanti al titolo della pagina nella struttura del documento.
    <div role="alert" aria-label="Avvisi per l'amministratore" className={`mb-6 rounded-xl border p-4 ${critico ? 'border-red-300 bg-red-50 text-red-900' : 'border-amber-300 bg-amber-50 text-amber-900'}`}>
      <div className="flex items-start justify-between gap-3">
        <p className="flex items-center gap-2 font-semibold"><AlertTriangle size={18} aria-hidden/>{elenco.length === 1 ? 'Un problema da guardare' : `${elenco.length} problemi da guardare`}</p>
        <button type="button" onClick={nascondi} title="Nascondi per un giorno" aria-label="Nascondi per un giorno" className="rounded p-1 hover:bg-black/5"><X size={16} aria-hidden/></button>
      </div>
      <ul className="mt-2 space-y-2 text-sm">
        {elenco.map((avviso) => <li key={avviso.codice}><strong>{avviso.titolo}.</strong> {avviso.dettaglio}</li>)}
      </ul>
      <p className="mt-3 text-sm"><Link to="/admin/settings" className="underline">Copie di sicurezza, spazio su disco e versione nelle Impostazioni</Link></p>
    </div>
  );
}
