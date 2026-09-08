import { useCallback, useEffect, useRef, useState } from 'react';
import type { Page } from '../types/api';

/** Quante voci arrivano per volta in una tendina di ricerca.
 *
 * Prima erano otto, prese una volta sola: il resto del catalogo non era
 * raggiungibile in nessun modo, né scorrendo né scrivendo (le otto erano
 * comunque le prime otto della ricerca). Venticinque riempiono il pannello
 * senza far aspettare, e le successive arrivano scorrendo.
 */
export const PAGINA_TENDINA = 25;

type Carica<T> = (query: { q?: string; page: number; page_size: number }) => Promise<Page<T>>;

interface Opzioni<T> {
  /** A false non interroga il server: per le tendine dentro una modale chiusa. */
  attiva?: boolean;
  /** Ogni pagina arrivata, per chi tiene una propria copia delle voci viste. */
  onPagina?: (voci: T[]) => void;
  onErrore?: (errore: unknown) => void;
}

/** Ricerca a pagine per una tendina: testo con attesa, poi altre voci a scorrimento.
 *
 * Le risposte fuori tempo massimo vengono scartate confrontando un numero di
 * richiesta: senza, la risposta lenta di una ricerca abbandonata sovrascriveva
 * quella giusta, e nella tendina comparivano le voci di ciò che si era appena
 * finito di cancellare.
 */
export function useTendinaPaginata<T extends { id: string }>(carica: Carica<T>, opzioni: Opzioni<T> = {}) {
  const { attiva = true } = opzioni;
  const [testo, setTesto] = useState('');
  const [voci, setVoci] = useState<T[]>([]);
  const [totale, setTotale] = useState(0);
  const [cercando, setCercando] = useState(false);
  const [caricandoAltre, setCaricandoAltre] = useState(false);
  const pagina = useRef(1);
  const richiesta = useRef(0);
  // Le funzioni arrivano nuove a ogni render: tenerle in un riferimento evita
  // che l'effetto riparta (e la ricerca si azzeri) a ogni battuta di tasto.
  const ultime = useRef({ carica, opzioni });
  ultime.current = { carica, opzioni };

  useEffect(() => {
    if (!attiva) return;
    setCercando(true);
    const timer = window.setTimeout(() => {
      const mia = (richiesta.current += 1);
      pagina.current = 1;
      void ultime.current
        .carica({ q: testo || undefined, page: 1, page_size: PAGINA_TENDINA })
        .then((risposta) => {
          if (mia !== richiesta.current) return;
          setVoci(risposta.items);
          setTotale(risposta.total);
          ultime.current.opzioni.onPagina?.(risposta.items);
        })
        .catch((errore) => { if (mia === richiesta.current) ultime.current.opzioni.onErrore?.(errore); })
        .finally(() => { if (mia === richiesta.current) setCercando(false); });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [testo, attiva]);

  const caricaAltre = useCallback(() => {
    if (cercando || caricandoAltre || voci.length >= totale) return;
    const mia = richiesta.current;
    const prossima = pagina.current + 1;
    setCaricandoAltre(true);
    void ultime.current
      .carica({ q: testo || undefined, page: prossima, page_size: PAGINA_TENDINA })
      .then((risposta) => {
        if (mia !== richiesta.current) return;
        pagina.current = prossima;
        setTotale(risposta.total);
        // L'ordinamento del server è stabile, ma una voce creata nel frattempo
        // può far scivolare le altre di una posizione: senza questo controllo
        // comparirebbe due volte.
        setVoci((precedenti) => {
          const viste = new Set(precedenti.map((voce) => voce.id));
          return [...precedenti, ...risposta.items.filter((voce) => !viste.has(voce.id))];
        });
        ultime.current.opzioni.onPagina?.(risposta.items);
      })
      .catch((errore) => { if (mia === richiesta.current) ultime.current.opzioni.onErrore?.(errore); })
      // Senza guardia: se nel frattempo è partita una nuova ricerca il flag
      // resterebbe acceso per sempre e non si caricherebbe più nulla.
      .finally(() => setCaricandoAltre(false));
  }, [cercando, caricandoAltre, voci.length, totale, testo]);

  return { testo, setTesto, voci, totale, cercando, caricandoAltre, caricaAltre };
}

/** Tutte le voci di un elenco, non le prime duecento.
 *
 * Serve alle tendine native `<select>`, che mostrano quello che hanno in
 * pancia: una voce non caricata lì non è troncata, è invisibile — e chi la
 * cerca conclude che non esista. Il ciclo si ferma da solo perché
 * l'ordinamento del server è stabile e il totale è noto.
 */
export async function tutteLeVoci<T>(carica: (query: { page: number; page_size: number }) => Promise<Page<T>>): Promise<T[]> {
  const PASSO = 200;
  let pagina = 1;
  let ultima = await carica({ page: pagina, page_size: PASSO });
  const voci = [...ultima.items];
  while (voci.length < ultima.total && ultima.items.length === PASSO) {
    pagina += 1;
    ultima = await carica({ page: pagina, page_size: PASSO });
    voci.push(...ultima.items);
  }
  return voci;
}
