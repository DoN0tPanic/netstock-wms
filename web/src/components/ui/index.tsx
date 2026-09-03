import { createContext, forwardRef, useCallback, useContext, useEffect, useMemo, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type SelectHTMLAttributes } from 'react';
import { Eye, EyeOff, Loader2, X } from 'lucide-react';

const join = (...values: Array<string | false | null | undefined>) => values.filter(Boolean).join(' ');
export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> { variant?: 'primary' | 'secondary' | 'danger' | 'ghost'; loading?: boolean }
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant = 'primary', loading, disabled, children, ...props }, ref) => <button ref={ref} disabled={disabled || loading} className={join('inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 font-medium transition disabled:cursor-not-allowed disabled:opacity-50', variant === 'primary' && 'bg-blue-600 text-white hover:bg-blue-700', variant === 'secondary' && 'border border-slate-300 bg-white hover:bg-slate-50', variant === 'danger' && 'bg-red-600 text-white hover:bg-red-700', variant === 'ghost' && 'hover:bg-slate-100', className)} {...props}>{loading ? <><Loader2 size={17} className="animate-spin" aria-hidden/>Attendere…</> : children}</button>);
Button.displayName = 'Button';
export interface InputProps extends InputHTMLAttributes<HTMLInputElement> { label?: string; error?: string; hint?: string }
export const Input = forwardRef<HTMLInputElement, InputProps>(({ label, error, hint, id, className, ...props }, ref) => { const inputId = id ?? props.name; return <label className="block text-sm font-medium text-slate-700" htmlFor={inputId}>{label && <span className="mb-1 block">{label}</span>}<input ref={ref} id={inputId} className={join('min-h-11 w-full rounded-lg border bg-white px-3 py-2 text-base', error ? 'border-red-500' : 'border-slate-300', className)} aria-invalid={Boolean(error)} aria-describedby={error ? `${inputId}-error` : undefined} {...props}/>{hint && !error && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}{error && <span id={`${inputId}-error`} className="mt-1 block text-sm text-red-700">{error}</span>}</label>; });
Input.displayName = 'Input';
/** Campo password con la possibilità di vedere quello che si sta scrivendo.
 *
 * Serve soprattutto sul telefono: la barra dei suggerimenti aggiunge spazi, il
 * maiuscolo automatico cambia la prima lettera, e con i pallini al posto dei
 * caratteri non c'è modo di accorgersene — si vede solo un rifiuto che sembra
 * la password sbagliata.
 *
 * Il campo torna nascosto quando lo si lascia: una password rimasta in chiaro
 * su uno schermo appoggiato al bancone è un problema diverso, ma reale.
 */
export const PasswordInput = forwardRef<HTMLInputElement, Omit<InputProps, 'type'>>(({ className, onBlur, ...props }, ref) => {
  const [visibile, setVisibile] = useState(false);
  return <div className="relative">
    <Input ref={ref} type={visibile ? 'text' : 'password'} className={join('pr-12', className)} onBlur={(event) => { setVisibile(false); onBlur?.(event); }} {...props}/>
    <button type="button" tabIndex={-1} aria-label={visibile ? 'Nascondi la password' : 'Mostra la password'} aria-pressed={visibile}
      className="absolute right-1 top-7 inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-700"
      onMouseDown={(event) => event.preventDefault()} onClick={() => setVisibile((valore) => !valore)}>
      {visibile ? <EyeOff size={19} aria-hidden/> : <Eye size={19} aria-hidden/>}
    </button>
  </div>;
});

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> { label?: string; error?: string }
export const Select = forwardRef<HTMLSelectElement, SelectProps>(({ label, error, id, children, className, ...props }, ref) => { const inputId = id ?? props.name; return <label className="block text-sm font-medium text-slate-700" htmlFor={inputId}>{label && <span className="mb-1 block">{label}</span>}<select ref={ref} id={inputId} className={join('min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 py-2', className)} {...props}>{children}</select>{error && <span className="mt-1 block text-sm text-red-700">{error}</span>}</label>; });
Select.displayName = 'Select';
export interface ComboboxOption { id: string; label: string; sublabel?: string }
export function Combobox({ label, placeholder, query, onQueryChange, options, loading, onSelect, selectedLabel, extraOption, disabled, hint }: { label?: string; placeholder?: string; query: string; onQueryChange: (value: string) => void; options: ComboboxOption[]; loading?: boolean; onSelect: (id: string) => void; selectedLabel?: string; extraOption?: { id: string; label: string }; disabled?: boolean; hint?: string }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const allOptions = extraOption ? [...options, extraOption] : options;
  useEffect(() => setActive(0), [options.length, extraOption?.id]);
  const choose = (id: string) => { onQueryChange(''); setOpen(false); onSelect(id); };
  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') { setOpen(false); return; }
    if (!open || !allOptions.length) return;
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive((current) => (current + 1) % allOptions.length); }
    if (event.key === 'ArrowUp') { event.preventDefault(); setActive((current) => (current - 1 + allOptions.length) % allOptions.length); }
    if (event.key === 'Enter') { event.preventDefault(); const option = allOptions[active]; if (option) choose(option.id); }
  };
  return <div className="relative">
    <label className="block text-sm font-medium text-slate-700">
      {label && <span className="mb-1 block">{label}</span>}
      <input disabled={disabled} className={join('min-h-11 w-full rounded-lg border bg-white px-3 py-2 text-base', 'border-slate-300')} placeholder={selectedLabel || placeholder} value={query} autoComplete="off" onChange={(event) => { onQueryChange(event.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onBlur={() => window.setTimeout(() => setOpen(false), 150)} onKeyDown={onKeyDown}/>
    </label>
    {selectedLabel && !query && <p className="mt-1 text-xs text-slate-600">Selezionato: <span className="font-medium">{selectedLabel}</span></p>}
    {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    {open && !disabled && <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-72 overflow-auto rounded-lg border bg-white py-1 shadow-xl" role="listbox">
      {loading && <p className="px-3 py-2 text-sm text-slate-500">Ricerca…</p>}
      {!loading && !options.length && <p className="px-3 py-2 text-sm text-slate-500">Nessun risultato.</p>}
      {options.map((option, index) => <button type="button" key={option.id} role="option" aria-selected={index === active} className={join('block w-full px-3 py-2 text-left text-sm', index === active ? 'bg-blue-50' : 'hover:bg-slate-50')} onMouseDown={(event) => event.preventDefault()} onClick={() => choose(option.id)} onMouseEnter={() => setActive(index)}>
        <span className="block font-medium">{option.label}</span>
        {option.sublabel && <span className="block text-xs text-slate-500">{option.sublabel}</span>}
      </button>)}
      {extraOption && <button type="button" className={join('block w-full border-t px-3 py-2 text-left text-sm font-medium text-blue-700', active === options.length ? 'bg-blue-50' : 'hover:bg-slate-50')} onMouseDown={(event) => event.preventDefault()} onClick={() => choose(extraOption.id)} onMouseEnter={() => setActive(options.length)}>{extraOption.label}</button>}
    </div>}
  </div>;
}
/** Riquadro di lavorazione in corso, con il tempo trascorso.
 *
 * Il contatore non è un vezzo: un messaggio fermo su un'operazione che dura
 * venti secondi è indistinguibile da una pagina bloccata, ed è esattamente il
 * dubbio che viene all'operatore. Un numero che sale dice che il lavoro c'è.
 *
 * Il tempo è marcato `aria-hidden` perché un lettore di schermo, con la
 * regione live, rileggerebbe la frase a ogni secondo.
 */
export function Busy({ title, children }: { title: string; children?: ReactNode }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return <section role="status" aria-live="polite" className="flex items-start gap-3 rounded-xl border border-blue-200 bg-blue-50 p-4 text-blue-900"><Loader2 size={19} className="mt-0.5 shrink-0 animate-spin" aria-hidden/><div className="min-w-0"><p className="font-medium">{title}<span className="ml-2 font-normal tabular-nums text-blue-800" aria-hidden>{seconds}s</span></p>{children && <div className="mt-0.5 text-sm">{children}</div>}</div></section>;
}

export const Badge = ({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'success' | 'warning' | 'danger' | 'info' | 'neutral' }) => <span className={join('inline-flex rounded-full px-2.5 py-1 text-xs font-semibold', tone === 'success' && 'bg-green-100 text-green-800', tone === 'warning' && 'bg-amber-100 text-amber-800', tone === 'danger' && 'bg-red-100 text-red-800', tone === 'info' && 'bg-blue-100 text-blue-800', tone === 'neutral' && 'bg-slate-100 text-slate-700')}>{children}</span>;
export function Modal({ open, title, children, onClose }: { open: boolean; title: string; children: ReactNode; onClose: () => void }) { useEffect(() => { if (!open) return; const handler = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); }; document.addEventListener('keydown', handler); return () => document.removeEventListener('keydown', handler); }, [open, onClose]); if (!open) return null; return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4" role="dialog" aria-modal="true" aria-labelledby="modal-title" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><div className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-xl bg-white p-5 shadow-xl"><div className="mb-4 flex items-center justify-between"><h2 id="modal-title" className="text-xl font-semibold">{title}</h2><button aria-label="Chiudi" onClick={onClose} className="rounded p-2"><X/></button></div>{children}</div></div>; }
export function Table<T>({ columns, rows, keyOf, empty }: { columns: Array<{ key: string; label: string; render: (row: T) => ReactNode }>; rows: T[]; keyOf: (row: T) => string; empty: ReactNode }) { if (!rows.length) return <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-slate-600">{empty}</div>; return <div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full text-left text-sm"><thead className="bg-slate-100"><tr>{columns.map((column) => <th scope="col" className="px-4 py-3 font-semibold" key={column.key}>{column.label}</th>)}</tr></thead><tbody className="divide-y">{rows.map((row) => <tr key={keyOf(row)} className="hover:bg-slate-50">{columns.map((column) => <td className="px-4 py-3" key={column.key}>{column.render(row)}</td>)}</tr>)}</tbody></table></div>; }
type ToastTone = 'success' | 'error' | 'info'; type ToastItem = { id: number; message: string; tone: ToastTone };
const ToastContext = createContext<{ show: (message: string, tone?: ToastTone) => void } | null>(null);
export function ToastProvider({ children }: { children: ReactNode }) { const [items, setItems] = useState<ToastItem[]>([]); const show = useCallback((message: string, tone: ToastTone = 'info') => { const id = Date.now() + Math.random(); setItems((current) => [...current, { id, message, tone }]); window.setTimeout(() => setItems((current) => current.filter((item) => item.id !== id)), 4500); }, []); const value = useMemo(() => ({ show }), [show]); return <ToastContext.Provider value={value}>{children}<div className="fixed bottom-4 right-4 z-[60] space-y-2" aria-live="polite">{items.map((item) => <div key={item.id} className={join('max-w-sm rounded-lg px-4 py-3 text-white shadow-lg', item.tone === 'success' && 'bg-green-700', item.tone === 'error' && 'bg-red-700', item.tone === 'info' && 'bg-slate-800')}>{item.message}</div>)}</div></ToastContext.Provider>; }
export const useToast = () => { const value = useContext(ToastContext); if (!value) throw new Error('useToast must be used inside ToastProvider'); return value; };
