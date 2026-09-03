import { forwardRef, useEffect, useMemo, useState, type KeyboardEvent } from 'react';
import { Search } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { searchApi } from '../api';
import type { SearchResult, SearchResultType } from '../types/api';

const labels: Record<SearchResultType, string> = { unit: 'Unità', catalog_item: 'Articolo', delivery_note: 'Bolla', location: 'Ubicazione' };
const noResults: SearchResult[] = [];
export const GlobalSearch = forwardRef<HTMLInputElement>(function GlobalSearch(_, ref) {
  const navigate = useNavigate(); const [value, setValue] = useState(''); const [debounced, setDebounced] = useState(''); const [open, setOpen] = useState(false); const [active, setActive] = useState(0);
  useEffect(() => { const timer = window.setTimeout(() => setDebounced(value.trim()), 250); return () => window.clearTimeout(timer); }, [value]);
  const query = useQuery({ queryKey: ['global-search', debounced], queryFn: () => searchApi.search(debounced), enabled: debounced.length >= 2 });
  const results = query.data?.results ?? noResults;
  const groups = useMemo(() => Object.entries(labels).map(([type, label]) => ({ type: type as SearchResultType, label, rows: results.filter((row) => row.type === type) })).filter((group) => group.rows.length), [results]);
  useEffect(() => setActive(0), [results]);
  const choose = (result: SearchResult) => { setOpen(false); setValue(''); void navigate(result.path); };
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => { if (event.key === 'Escape') { setOpen(false); return; } if (!open || !results.length) return; if (event.key === 'ArrowDown') { event.preventDefault(); setActive((current) => (current + 1) % results.length); } if (event.key === 'ArrowUp') { event.preventDefault(); setActive((current) => (current - 1 + results.length) % results.length); } if (event.key === 'Enter') { event.preventDefault(); const result = results[active]; if (result) choose(result); } };
  return <div className="relative w-full max-w-xl px-3"><Search className="pointer-events-none absolute left-6 top-1/2 -translate-y-1/2 text-slate-400" size={18}/><input ref={ref} aria-label="Ricerca globale" className="min-h-10 w-full rounded-lg border border-slate-300 bg-slate-50 py-2 pl-10 pr-3 text-sm focus:bg-white" placeholder="Cerca seriale, articolo, bolla, ubicazione…" value={value} onChange={(event) => { setValue(event.target.value); setOpen(true); }} onFocus={() => setOpen(true)} onBlur={() => window.setTimeout(() => setOpen(false), 150)} onKeyDown={onKeyDown}/>{open && debounced.length >= 2 && <div className="absolute left-3 right-3 top-full z-50 mt-1 max-h-96 overflow-auto rounded-lg border bg-white py-2 shadow-xl" role="listbox">{query.isLoading && <p className="px-4 py-3 text-sm text-slate-500">Ricerca…</p>}{!query.isLoading && !results.length && <p className="px-4 py-3 text-sm text-slate-500">Nessun risultato.</p>}{groups.map((group) => <div key={group.type}><p className="px-4 pb-1 pt-2 text-xs font-semibold uppercase text-slate-500">{group.label}</p>{group.rows.map((result) => { const index = results.indexOf(result); return <button type="button" role="option" aria-selected={index === active} className={`block w-full px-4 py-2 text-left text-sm ${index === active ? 'bg-blue-50' : 'hover:bg-slate-50'}`} key={`${result.type}:${result.id}`} onMouseDown={(event) => event.preventDefault()} onClick={() => choose(result)} onMouseEnter={() => setActive(index)}><span className="block font-medium">{result.label}</span>{result.sublabel && <span className="block text-xs text-slate-500">{result.sublabel}</span>}</button>; })}</div>)}</div>}</div>;
});
