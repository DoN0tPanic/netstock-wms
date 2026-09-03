import { BarcodeFormat, BrowserMultiFormatReader, DecodeHintType, NotFoundException } from '@zxing/library';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Flashlight, FlashlightOff, SwitchCamera } from 'lucide-react';
import { Button } from '../ui';

/** Come il genitore ha giudicato il codice appena letto. Serve a dare in
 *  sovrimpressione lo stesso responso che si vedrebbe nel modulo dietro alla
 *  fotocamera — che, con la fotocamera aperta, non si vede. */
export type EsitoLettura = 'valid' | 'warning' | 'duplicate';

// I formati che stanno davvero sulle etichette degli apparati di rete. Il
// lettore predefinito prova una ventina di simbologie a ogni fotogramma:
// dirgli quali cercare è la differenza fra una lettura in mezzo secondo e una
// che sembra non arrivare mai.
const FORMATI = [
  BarcodeFormat.CODE_128, BarcodeFormat.CODE_39, BarcodeFormat.CODE_93,
  BarcodeFormat.ITF, BarcodeFormat.DATA_MATRIX, BarcodeFormat.QR_CODE,
  BarcodeFormat.EAN_13, BarcodeFormat.UPC_A,
];
const HINTS = new Map<DecodeHintType, unknown>([[DecodeHintType.POSSIBLE_FORMATS, FORMATI]]);

// `torch` e `focusMode` esistono su Android ma non nei tipi standard di
// TypeScript: sono estensioni ancora in bozza. Il codice le prova e accetta
// che non ci siano, invece di dare per scontato che ci siano.
type VincoliEstesi = MediaTrackConstraintSet & { torch?: boolean; focusMode?: string };
type CapacitaEstese = MediaTrackCapabilities & { torch?: boolean };

const vibra = (schema: number | number[]) => {
  if (typeof navigator.vibrate === 'function') navigator.vibrate(schema);
};

/** Fotocamera per la lettura dei barcode.
 *
 * Con `continuo` non si chiude a ogni codice: resta aperta e legge il
 * successivo. È il caso per cui esiste — ventiquattro apparati in fila — e
 * senza di esso ogni pezzo costa un'apertura e una chiusura della finestra.
 *
 * Il giudizio su cosa è stato letto non sta qui: `onDetected` lo restituisce,
 * perché le regole su duplicati e formato appartengono a chi raccoglie i
 * seriali, non a chi guarda dentro l'obiettivo.
 */
export function BarcodeCamera({ onDetected, onClose, continuo = false, progresso }: {
  onDetected: (value: string) => EsitoLettura | void;
  onClose: () => void;
  continuo?: boolean;
  progresso?: { letti: number; attesi: number };
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState('');
  const [camere, setCamere] = useState<MediaDeviceInfo[]>([]);
  const [scelta, setScelta] = useState<string | null>(null);
  const [torcia, setTorcia] = useState(false);
  const [torciaDisponibile, setTorciaDisponibile] = useState(false);
  const [letture, setLetture] = useState<Array<{ id: number; valore: string; esito: EsitoLettura }>>([]);
  const [lampo, setLampo] = useState<EsitoLettura | null>(null);
  const ultima = useRef({ valore: '', quando: 0 });
  const audio = useRef<AudioContext | null>(null);
  // La funzione del genitore cambia identità a ogni suo render — e in modalità
  // continua ne provoca uno a ogni seriale accettato. Se stesse fra le
  // dipendenze dell'effetto, la fotocamera si spegnerebbe e riaccenderebbe
  // dopo ogni lettura.
  const chiamata = useRef(onDetected);
  chiamata.current = onDetected;

  const suona = useCallback((esito: EsitoLettura) => {
    try {
      audio.current ??= new AudioContext();
      const contesto = audio.current;
      const nota = contesto.createOscillator();
      const volume = contesto.createGain();
      nota.frequency.value = esito === 'valid' ? 880 : esito === 'warning' ? 620 : 300;
      volume.gain.setValueAtTime(0.12, contesto.currentTime);
      volume.gain.exponentialRampToValueAtTime(0.001, contesto.currentTime + 0.14);
      nota.connect(volume).connect(contesto.destination);
      nota.start();
      nota.stop(contesto.currentTime + 0.15);
    } catch {
      // Nessun audio: in magazzino la vibrazione basta, e su un desktop senza
      // permessi audio non è un errore da mostrare.
    }
  }, []);

  useEffect(() => {
    const reader = new BrowserMultiFormatReader(HINTS);
    let attivo = true;

    const gestisci = (grezzo: string) => {
      const valore = grezzo.trim();
      if (!valore) return;
      // Finché il codice resta inquadrato il lettore lo rilegge molte volte al
      // secondo: senza questa finestra una scansione diventerebbe venti.
      const ora = Date.now();
      if (valore === ultima.current.valore && ora - ultima.current.quando < 2000) return;
      ultima.current = { valore, quando: ora };

      const esito = chiamata.current(valore) ?? 'valid';
      vibra(esito === 'valid' ? 60 : esito === 'warning' ? [40, 60, 40] : [90, 70, 90]);
      suona(esito);
      setLampo(esito);
      window.setTimeout(() => setLampo(null), 350);
      if (continuo) setLetture((vecchie) => [{ id: ora, valore, esito }, ...vecchie].slice(0, 3));
    };

    // `facingMode: environment` senza `exact`: sul telefono prende la
    // posteriore principale, su un portatile ripiega sull'unica che c'è invece
    // di fallire. La risoluzione alta serve a leggere i codici piccoli e fitti
    // delle etichette di serie.
    const vincoli: MediaStreamConstraints = {
      video: scelta
        ? { deviceId: { exact: scelta }, width: { ideal: 1920 }, height: { ideal: 1080 } }
        : {
            facingMode: { ideal: 'environment' },
            width: { ideal: 1920 }, height: { ideal: 1080 },
            advanced: [{ focusMode: 'continuous' } as VincoliEstesi],
          },
    };

    void reader.decodeFromConstraints(vincoli, videoRef.current!, (result, scanError) => {
      if (!attivo) return;
      if (result) gestisci(result.getText());
      // `NotFoundException` è la normalità: significa "in questo fotogramma non
      // c'era un codice". Segnalarla riempirebbe lo schermo di errori mentre si
      // sta semplicemente inquadrando.
      if (scanError && !(scanError instanceof NotFoundException)) {
        setError('Lettura difficile: avvicina la fotocamera e tieni fermo.');
      }
    }).then(async () => {
      if (!attivo) return;
      setError('');
      const traccia = (videoRef.current?.srcObject as MediaStream | null)?.getVideoTracks()[0];
      setTorciaDisponibile(Boolean((traccia?.getCapabilities?.() as CapacitaEstese | undefined)?.torch));
      // L'elenco ha le etichette solo dopo che il permesso è stato dato: prima
      // sarebbero voci vuote fra cui non si può scegliere.
      const elenco = await navigator.mediaDevices.enumerateDevices();
      if (attivo) setCamere(elenco.filter((device) => device.kind === 'videoinput'));
    }).catch((reason: unknown) => {
      if (!attivo) return;
      const nome = reason instanceof Error ? reason.name : '';
      setError(nome === 'NotAllowedError'
        ? 'Permesso negato: autorizza la fotocamera per questo sito e riapri.'
        : nome === 'NotFoundError'
          ? 'Nessuna fotocamera disponibile su questo dispositivo.'
          : 'Fotocamera non disponibile. Puoi scrivere il seriale a mano.');
    });

    return () => { attivo = false; reader.reset(); setTorcia(false); };
  }, [scelta, continuo, suona]);

  const cambiaTorcia = async () => {
    const traccia = (videoRef.current?.srcObject as MediaStream | null)?.getVideoTracks()[0];
    if (!traccia) return;
    try {
      await traccia.applyConstraints({ advanced: [{ torch: !torcia } as VincoliEstesi] });
      setTorcia(!torcia);
    } catch { setTorciaDisponibile(false); }
  };

  // La posteriore scelta dal browser non è sempre quella giusta: sui telefoni
  // recenti ce ne sono tre, e la grandangolare non mette a fuoco da vicino —
  // proprio la distanza a cui si legge un'etichetta.
  const cambiaCamera = () => {
    if (camere.length < 2) return;
    const attuale = camere.findIndex((device) => device.deviceId === scelta);
    const prossima = camere[(attuale + 1) % camere.length];
    if (prossima) setScelta(prossima.deviceId);
  };

  const bordo = lampo === 'valid' ? 'ring-4 ring-green-400'
    : lampo === 'warning' ? 'ring-4 ring-amber-400'
    : lampo === 'duplicate' ? 'ring-4 ring-red-500' : '';

  return <div className="space-y-3">
    <div className={`relative overflow-hidden rounded-lg bg-black transition ${bordo}`}>
      {/* Verticale sul telefono: un riquadro 16:9 dentro una finestra su uno
          schermo in piedi lascia l'immagine alta due dita, e a quella
          dimensione un barcode non si inquadra. */}
      <video ref={videoRef} className="aspect-[3/4] w-full object-cover sm:aspect-video" muted playsInline/>
      {/* Il mirino non serve al lettore, che guarda tutto il fotogramma: serve
          a chi inquadra, per sapere quanto avvicinarsi. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <div className="h-24 w-4/5 rounded-lg border-2 border-white/80 shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]"/>
      </div>
      {progresso && <p className="absolute left-3 top-3 rounded-full bg-black/60 px-3 py-1 text-sm font-semibold text-white tabular-nums" aria-live="polite">{progresso.letti} / {progresso.attesi}</p>}
      <div className="absolute right-3 top-3 flex gap-2">
        {torciaDisponibile && <button type="button" aria-label={torcia ? 'Spegni la torcia' : 'Accendi la torcia'} aria-pressed={torcia} className="rounded-full bg-black/60 p-3 text-white" onClick={() => void cambiaTorcia()}>{torcia ? <Flashlight size={20}/> : <FlashlightOff size={20}/>}</button>}
        {camere.length > 1 && <button type="button" aria-label="Cambia fotocamera" className="rounded-full bg-black/60 p-3 text-white" onClick={cambiaCamera}><SwitchCamera size={20}/></button>}
      </div>
      {continuo && letture.length > 0 && <ul className="absolute inset-x-3 bottom-3 space-y-1">{letture.map((lettura) => <li key={lettura.id} className={`rounded-lg px-3 py-1.5 font-mono text-sm text-white ${lettura.esito === 'valid' ? 'bg-green-700/90' : lettura.esito === 'warning' ? 'bg-amber-600/90' : 'bg-red-700/90'}`}>{lettura.valore}{lettura.esito === 'duplicate' && <span className="font-sans"> · già letto</span>}{lettura.esito === 'warning' && <span className="font-sans"> · formato inatteso</span>}</li>)}</ul>}
    </div>
    <p className="text-sm">{continuo
      ? 'Inquadra un barcode alla volta: la fotocamera resta aperta e passa al successivo da sola.'
      : 'Inquadra il barcode mantenendolo fermo e ben illuminato.'}</p>
    {error && <p className="text-red-700" role="alert">{error}</p>}
    <Button variant="secondary" onClick={onClose}>{continuo ? 'Ho finito' : 'Chiudi fotocamera'}</Button>
  </div>;
}
