import { useEffect, useRef, useState } from 'react';
import { Camera, Plus } from 'lucide-react';
import { Button, Input, Modal } from '../ui';
import { BarcodeCamera } from './BarcodeCamera';
import { normalizeSerial, validateSerialPattern } from '../../lib/validation';
export type SerialFeedback = 'valid' | 'warning' | 'duplicate' | null;
export function SerialInput({ acquired, expected, serialPattern, onConfirm, disabled = false }: { acquired: string[]; expected: number; serialPattern?: string | null; onConfirm: (serial: string, feedback: Exclude<SerialFeedback, null>) => void; disabled?: boolean }) {
  const [value, setValue] = useState(''); const [feedback, setFeedback] = useState<SerialFeedback>(null); const [camera, setCamera] = useState(false); const inputRef = useRef<HTMLInputElement>(null);
  // Con la fotocamera aperta il fuoco non va rimesso sul campo: su Android
  // farebbe salire la tastiera virtuale sopra l'immagine, esattamente mentre
  // si sta inquadrando il codice successivo.
  const focus = () => { if (!disabled && !camera) inputRef.current?.focus(); };
  useEffect(focus, [acquired.length, disabled, camera]);
  // Shared by the keyboard/scanner-gun path, the "Aggiungi" button and the
  // camera, so a serial always goes through the same duplicate and pattern
  // checks however it was captured. Il responso torna al chiamante perché la
  // fotocamera, che copre il modulo, possa mostrarlo in sovrimpressione.
  const accept = (raw: string): Exclude<SerialFeedback, null> | undefined => { const serial = normalizeSerial(raw); if (!serial) return undefined; const state: Exclude<SerialFeedback, null> = acquired.includes(serial) ? 'duplicate' : validateSerialPattern(serial, serialPattern) ? 'valid' : 'warning'; setFeedback(state); if (state !== 'duplicate') { onConfirm(serial, state); setValue(''); } window.setTimeout(() => setFeedback(null), 1200); focus(); return state; };
  return <section className="rounded-xl border bg-white p-4" onClick={focus}>
    <div className="mb-3 flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">Acquisizione seriali</h3><div className="flex items-center gap-3"><span className="text-lg font-bold" aria-live="polite">{acquired.length} / {expected} acquisiti</span><Button type="button" variant="secondary" disabled={disabled} onClick={(event) => { event.stopPropagation(); setCamera(true); }}><Camera size={17}/>Fotocamera</Button></div></div>
    <div className="flex items-end gap-2">
      <div className="min-w-0 flex-1">
        {/* Autocorrect and auto-capitalisation on a phone silently rewrite a
            serial as you type it, so both are turned off here. `enterKeyHint`
            makes the virtual keyboard show a confirm key instead of a
            newline — but on mobile that key is unreliable, hence the button
            next to the field. */}
        <Input ref={inputRef} label="Numero seriale" value={value} disabled={disabled} onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); accept(value); } }} autoComplete="off" autoCorrect="off" autoCapitalize="characters" spellCheck={false} enterKeyHint="done" className={feedback === 'valid' ? 'border-green-600 bg-green-50' : feedback === 'warning' ? 'border-amber-500 bg-amber-50' : feedback === 'duplicate' ? 'border-red-600 bg-red-50' : ''} aria-label="Numero seriale" hint="Scansiona, inquadra col barcode o digita e tocca Aggiungi. Il campo resta pronto per il successivo."/>
      </div>
      <Button type="button" className="mb-[1.375rem] shrink-0" disabled={disabled || !value.trim()} onClick={(event) => { event.stopPropagation(); accept(value); }}><Plus size={18}/>Aggiungi</Button>
    </div>
    <div className="mt-2 min-h-6 text-sm" aria-live="assertive">{feedback === 'valid' && <span className="text-green-700">Seriale acquisito.</span>}{feedback === 'warning' && <span className="text-amber-700">Formato inatteso: acquisito, verifica il valore.</span>}{feedback === 'duplicate' && <span className="text-red-700">Seriale già presente nella lista.</span>}</div>
    {/* Lettura continua: la finestra resta aperta e ogni codice si aggiunge
        alla lista. Chiuderla a ogni pezzo significava, su ventiquattro
        apparati, ventiquattro aperture — ed è il gesto che questo modulo
        esiste per rendere veloce. */}
    <Modal open={camera} title="Inquadra i barcode dei seriali" onClose={() => setCamera(false)}><BarcodeCamera continuo progresso={{ letti: acquired.length, attesi: expected }} onDetected={(serial) => accept(serial)} onClose={() => setCamera(false)}/></Modal>
  </section>;
}
