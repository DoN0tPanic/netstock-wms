import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { MISURA_PAGINA, useElencoPaginato } from './elencoPaginato';
import type { Page } from '../types/api';

type Voce = { id: string };
const pagina = (voci: Voce[], total: number, page = 1): Page<Voce> => ({ items: voci, total, page, page_size: MISURA_PAGINA });
const nVoci = (da: number, quante: number) => Array.from({ length: quante }, (_, i) => ({ id: `id-${da + i}` }));

const involucro = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
};

describe('anagrafica sfogliabile', () => {
  it('chiede una pagina per volta, non l’elenco intero', async () => {
    const carica = vi.fn().mockResolvedValue(pagina(nVoci(0, 50), 8011));
    const { result } = renderHook(() => useElencoPaginato<Voce>('prova', carica), { wrapper: involucro() });

    await waitFor(() => expect(result.current.query.data).toBeDefined());
    expect(carica).toHaveBeenCalledWith({ q: undefined, page: 1, page_size: 50 });
    expect(carica).toHaveBeenCalledTimes(1);
    expect(result.current.query.data?.total).toBe(8011);
  });

  it('sfogliando chiede la pagina chiesta', async () => {
    const carica = vi.fn().mockResolvedValue(pagina(nVoci(0, 50), 8011));
    const { result } = renderHook(() => useElencoPaginato<Voce>('prova2', carica), { wrapper: involucro() });
    await waitFor(() => expect(result.current.query.data).toBeDefined());

    act(() => result.current.vaiAPagina(3));

    await waitFor(() => expect(carica).toHaveBeenLastCalledWith({ q: undefined, page: 3, page_size: 50 }));
  });

  it('cercando riparte dalla prima pagina', async () => {
    // Restare sulla settima pagina di un elenco che ora ne ha due mostrerebbe
    // una tabella vuota, e sembrerebbe che la ricerca non abbia trovato nulla.
    const carica = vi.fn().mockResolvedValue(pagina(nVoci(0, 50), 8011));
    const { result } = renderHook(() => useElencoPaginato<Voce>('prova3', carica), { wrapper: involucro() });
    await waitFor(() => expect(result.current.query.data).toBeDefined());
    act(() => result.current.vaiAPagina(7));
    await waitFor(() => expect(carica).toHaveBeenLastCalledWith({ q: undefined, page: 7, page_size: 50 }));

    act(() => result.current.setTesto('c9200'));

    await waitFor(() => expect(carica).toHaveBeenLastCalledWith({ q: 'c9200', page: 1, page_size: 50 }));
    expect(result.current.pagina).toBe(1);
  });

  it('aspetta la fine della digitazione prima di interrogare', async () => {
    const carica = vi.fn().mockResolvedValue(pagina(nVoci(0, 50), 8011));
    const { result } = renderHook(() => useElencoPaginato<Voce>('prova4', carica), { wrapper: involucro() });
    await waitFor(() => expect(result.current.query.data).toBeDefined());
    const prima = carica.mock.calls.length;

    act(() => { result.current.setTesto('c'); });
    act(() => { result.current.setTesto('c9'); });
    act(() => { result.current.setTesto('c92'); });

    await waitFor(() => expect(carica).toHaveBeenLastCalledWith({ q: 'c92', page: 1, page_size: 50 }));
    // Una sola interrogazione in più, non una per lettera.
    expect(carica.mock.calls.length).toBe(prima + 1);
  });
});
