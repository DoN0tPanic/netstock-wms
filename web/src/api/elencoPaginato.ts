import { useEffect, useState } from 'react';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import type { Page } from '../types/api';

/** Quante righe per pagina nelle anagrafiche. */
export const MISURA_PAGINA = 50;

export interface ElencoPaginato<T> {
  query: UseQueryResult<Page<T>>;
  testo: string;
  setTesto: (valore: string) => void;
  pagina: number;
  vaiAPagina: (numero: number) => void;
}

/** Un'anagrafica sfogliabile: ricerca sul server, una pagina per volta.
 *
 * Prima queste pagine scaricavano l'elenco intero e lo disegnavano tutto: con
 * ottomila articoli erano quarantuno richieste in fila e ottomila righe in una
 * tabella sola. Cercare in una tabella così non si può, e nemmeno scorrerla:
 * la ricerca la fa il server, che ha gli indici per farla.
 */
export function useElencoPaginato<T>(
  chiave: string,
  carica: (parametri: { q?: string; page: number; page_size: number }) => Promise<Page<T>>,
): ElencoPaginato<T> {
  const [testo, setTesto] = useState('');
  const [ricerca, setRicerca] = useState('');
  const [pagina, vaiAPagina] = useState(1);

  useEffect(() => {
    const timer = window.setTimeout(() => setRicerca(testo), 300);
    return () => window.clearTimeout(timer);
  }, [testo]);

  // Cambiare ricerca riporta alla prima pagina: restare sulla settima di un
  // elenco che ora ne ha due mostrerebbe una tabella vuota senza spiegazione,
  // e sembrerebbe che la ricerca non abbia trovato niente.
  useEffect(() => vaiAPagina(1), [ricerca]);

  const query = useQuery({
    queryKey: [chiave, { q: ricerca, page: pagina }],
    queryFn: () => carica({ q: ricerca || undefined, page: pagina, page_size: MISURA_PAGINA }),
    // Tenere la pagina precedente mentre arriva la successiva: senza, la
    // tabella lampeggia vuota a ogni clic e sembra che i dati siano spariti.
    placeholderData: (precedente) => precedente,
  });

  return { query, testo, setTesto, pagina, vaiAPagina };
}
