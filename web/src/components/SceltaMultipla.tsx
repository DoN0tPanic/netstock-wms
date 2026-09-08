import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown } from 'lucide-react';

export interface VoceScelta { id: string; etichetta: string }

/** Scelta multipla: un pulsante che dice cosa è selezionato e un pannello di
 * caselle da spuntare.
 *
 * Non è un `<select multiple>`: quello mostra tutte le voci insieme, occupa
 * l'altezza di una lista e per selezionarne due lontane pretende il tasto
 * Ctrl — una cosa che si spiega, e che su un telefono non esiste proprio.
 * Qui si apre, si spunta, si chiude, e il pulsante riassume.
 */
export function SceltaMultipla({ etichetta, vuoto, voci, scelte, onCambia }: {
  etichetta: string;
  vuoto: string;
  voci: VoceScelta[];
  scelte: string[];
  onCambia: (scelte: string[]) => void;
}) {
  const [aperto, setAperto] = useState(false);
  const contenitore = useRef<HTMLDivElement>(null);

  // Si chiude cliccando fuori e con Esc: un pannello che resta aperto sopra la
  // tabella dei risultati impedisce di vedere l'effetto di quello che si è
  // appena spuntato.
  useEffect(() => {
    if (!aperto) return;
    const fuori = (evento: MouseEvent) => {
      if (!contenitore.current?.contains(evento.target as Node)) setAperto(false);
    };
    const esc = (evento: KeyboardEvent) => { if (evento.key === 'Escape') setAperto(false); };
    document.addEventListener('mousedown', fuori);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', fuori); document.removeEventListener('keydown', esc); };
  }, [aperto]);

  const alterna = (id: string) =>
    onCambia(scelte.includes(id) ? scelte.filter((x) => x !== id) : [...scelte, id]);
  const riassunto = scelte.length === 0
    ? vuoto
    : scelte.length === 1
      ? voci.find((v) => v.id === scelte[0])?.etichetta ?? '1 selezionata'
      : `${scelte.length} selezionate`;

  return (
    <div className="relative" ref={contenitore}>
      <button type="button" aria-label={etichetta} aria-expanded={aperto} aria-haspopup="listbox"
        onClick={() => setAperto((v) => !v)}
        className={`flex min-h-11 w-full items-center justify-between gap-2 rounded-lg border bg-white px-3 py-2 text-left ${scelte.length ? 'border-blue-500' : 'border-slate-300'}`}>
        <span className="truncate">{riassunto}</span>
        <ChevronDown size={17} className="shrink-0 text-slate-500" aria-hidden/>
      </button>
      {aperto && (
        <div role="listbox" aria-multiselectable="true"
          // Il pannello è largo quanto i nomi, non quanto la colonna del
          // filtro: un'ubicazione si chiama «Deposito 38 › Scaffale badge», e
          // troncata a metà non si distingue da quella accanto. Il pulsante
          // sopra resta stretto, il pannello si allarga fin dove serve.
          className="absolute z-20 mt-1 max-h-72 w-max min-w-full max-w-[24rem] overflow-auto rounded-lg border border-slate-300 bg-white py-1 shadow-lg">
          <button type="button" role="option" aria-selected={scelte.length === 0}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-slate-100"
            onClick={() => onCambia([])}>
            <span className="w-4">{scelte.length === 0 && <Check size={15} aria-hidden/>}</span>{vuoto}
          </button>
          {voci.map((voce) => (
            <button key={voce.id} type="button" role="option" aria-selected={scelte.includes(voce.id)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-slate-100"
              onClick={() => alterna(voce.id)}>
              <span className="w-4">{scelte.includes(voce.id) && <Check size={15} className="text-blue-700" aria-hidden/>}</span>
              <span>{voce.etichetta}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
