import { useEffect, useState } from 'react';

/** Vero su uno schermo da telefono (sotto il breakpoint `md` di Tailwind).
 *
 * Serve dove la differenza fra telefono e scrivania non è di impaginazione ma
 * di **struttura** — una pagina unica contro un percorso a passi — e quindi
 * non si può esprimere con una classe CSS.
 *
 * Il valore iniziale è letto subito, non dopo il primo render: partire da
 * `false` farebbe comparire per un istante la pagina intera sul telefono,
 * proprio quella che si sta cercando di non mostrare.
 */
export function useSchermoStretto(query = '(max-width: 767px)') {
  const [stretto, setStretto] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia(query).matches);

  useEffect(() => {
    const media = window.matchMedia(query);
    const aggiorna = () => setStretto(media.matches);
    aggiorna();
    media.addEventListener('change', aggiorna);
    return () => media.removeEventListener('change', aggiorna);
  }, [query]);

  return stretto;
}
