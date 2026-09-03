import { useEffect, useState } from 'react';
import { AlertTriangle, PackagePlus, Sparkles } from 'lucide-react';
import type { DocumentAnalysis, ProposedLine } from '../../types/api';
import { Badge, Busy, Button } from '../ui';

const keyOf = (line: ProposedLine, index: number) =>
  `${index}-${line.position}-${line.part_number ?? line.supplier_code ?? ''}`;

/** Pannello della lettura strutturale della bolla.
 *
 * Non applica mai niente da solo: mostra cosa ha capito il modello, riga per
 * riga, e l'operatore sceglie cosa portare nel form. È la stessa regola che
 * vale per l'estrazione di un singolo campo — la revisione umana è parte del
 * progetto, non un ripiego.
 */
export function DeliveryNoteProposal({
  analysis,
  onApply,
  onCreateItem,
}: {
  analysis: DocumentAnalysis | null;
  onApply: (lines: ProposedLine[]) => void;
  onCreateItem: (line: ProposedLine) => void;
}) {
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  // Appena arriva la lettura, le righe che hanno già un articolo a catalogo
  // sono spuntate: sono quelle pronte da usare. Le altre chiedono prima di
  // creare l'articolo, quindi partono deselezionate.
  useEffect(() => {
    if (analysis?.status !== 'done') return;
    setSelected(
      Object.fromEntries(
        analysis.lines.map((line, index) => [keyOf(line, index), Boolean(line.catalog_item)]),
      ),
    );
  }, [analysis]);

  if (!analysis) return null;

  if (analysis.status === 'running') {
    return (
      <Busy title="Lettura del documento in corso…">
        Intanto puoi lavorare normalmente qui sotto: quando è pronta te la propongo.
        Su una macchina senza scheda video può richiedere qualche minuto.
      </Busy>
    );
  }

  if (analysis.status === 'failed') {
    return (
      <section role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-amber-900">
        <p className="font-medium">La lettura automatica non è riuscita.</p>
        <p className="text-sm">Compila le righe a mano: il resto del modulo funziona normalmente.</p>
      </section>
    );
  }

  if (!analysis.lines.length) {
    return (
      <section className="rounded-xl border border-slate-300 bg-slate-50 p-4">
        <p className="font-medium">Nessuna riga riconosciuta nel documento.</p>
        <p className="text-sm text-slate-600">
          Succede con le foto poco leggibili o con le pagine di continuazione. Fotografa tutte
          le pagine insieme, oppure inserisci le righe a mano.
        </p>
      </section>
    );
  }

  const chosen = analysis.lines.filter((line, index) => selected[keyOf(line, index)] && line.catalog_item);

  return (
    <section className="space-y-3 rounded-xl border border-green-300 bg-green-50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <Sparkles size={19} />
            Lettura del documento
          </h2>
          <p className="text-sm text-slate-700">
            {analysis.lines.length} righe di merce riconosciute in {(analysis.duration_ms / 1000).toFixed(1)} s.
            Controlla e scegli cosa portare nel modulo: nulla viene registrato finché non confermi.
          </p>
        </div>
        <Button type="button" disabled={!chosen.length} onClick={() => onApply(chosen)}>
          Usa {chosen.length} {chosen.length === 1 ? 'riga' : 'righe'}
        </Button>
      </div>

      <ul className="space-y-2">
        {analysis.lines.map((line, index) => {
          const key = keyOf(line, index);
          const known = Boolean(line.catalog_item);
          return (
            <li key={key} className="rounded-lg border bg-white p-3">
              <div className="flex flex-wrap items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-1 h-5 w-5 shrink-0"
                  checked={Boolean(selected[key])}
                  disabled={!known}
                  aria-label={`Includi la riga ${line.position || index + 1}`}
                  onChange={(event) => setSelected((old) => ({ ...old, [key]: event.target.checked }))}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs text-slate-500">Pos. {line.position || '—'}</span>
                    <strong className="font-mono">{line.part_number ?? line.supplier_code ?? '—'}</strong>
                    {known ? (
                      <Badge tone="success">A catalogo: {line.catalog_item?.part_number}</Badge>
                    ) : (
                      <Badge tone="warning">Non a catalogo</Badge>
                    )}
                  </div>
                  <p className="text-sm text-slate-700">{line.description || '—'}</p>
                  <p className="mt-1 text-sm">
                    Quantità <strong>{line.quantity ?? '—'}</strong>
                    {line.quantity_ordered && line.quantity_ordered !== line.quantity && (
                      <span className="text-slate-500"> (ordinati {line.quantity_ordered})</span>
                    )}
                    {line.serials.length > 0 && <> · {line.serials.length} seriali letti</>}
                  </p>
                  {line.serials.length > 0 && (
                    <p className="mt-1 break-all font-mono text-xs text-slate-600">
                      {line.serials.slice(0, 6).join(' · ')}
                      {line.serials.length > 6 && ` … e altri ${line.serials.length - 6}`}
                    </p>
                  )}
                  {line.secondary_serials.length > 0 && (
                    <p className="mt-1 text-xs text-slate-500">
                      {line.secondary_serials.length} seriali secondari (SN2) presenti sul documento:
                      non vengono caricati come pezzi.
                    </p>
                  )}
                  {!known && (
                    <p className="mt-1 flex items-start gap-1 text-sm text-amber-800">
                      <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                      Questo modello non è ancora a catalogo: crealo per poter ricevere la riga.
                    </p>
                  )}
                  {line.warnings.map((warning) => (
                    <p key={warning} className="mt-1 flex items-start gap-1 text-sm text-amber-800">
                      <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                      {warning}
                    </p>
                  ))}
                </div>
                {!known && (
                  <Button type="button" variant="secondary" onClick={() => onCreateItem(line)}>
                    <PackagePlus size={17} />
                    Crea a catalogo
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {analysis.non_goods.length > 0 && (
        <p className="text-sm text-slate-600">
          Righe ignorate perché non sono merce: {analysis.non_goods.join(', ')}.
        </p>
      )}
      {analysis.unassigned_serials.length > 0 && (
        <p className="text-sm text-amber-800">
          {analysis.unassigned_serials.length} seriali compaiono prima della prima riga
          riconosciuta — di solito proseguono dalla pagina precedente: {analysis.unassigned_serials.slice(0, 5).join(', ')}
          {analysis.unassigned_serials.length > 5 && '…'}
        </p>
      )}
    </section>
  );
}
