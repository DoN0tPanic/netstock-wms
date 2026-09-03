import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiDownload } from './client';

const rispostaVuota = () => new Response('', { status: 200 });

afterEach(() => { vi.restoreAllMocks(); });

const indirizzoChiamato = async (query: Record<string, string | number | boolean | null | undefined>) => {
  const fetchFinto = vi.spyOn(globalThis, 'fetch').mockResolvedValue(rispostaVuota());
  await apiDownload('/inventory/export', query);
  return new URL(fetchFinto.mock.calls[0]![0] as unknown as string);
};

describe('apiDownload', () => {
  it('non manda i filtri lasciati vuoti', async () => {
    // Il difetto vero: un filtro vuoto partiva come `location=`, e l'endpoint
    // che lo dichiara UUID rispondeva 422. Cioè «Esporta CSV» falliva sempre,
    // perché i filtri vuoti sono la condizione normale della pagina.
    const url = await indirizzoChiamato({ format: 'csv', q: '', location: '', vendor: '', status: 'in_stock' });

    expect(url.searchParams.get('format')).toBe('csv');
    expect(url.searchParams.get('status')).toBe('in_stock');
    expect(url.searchParams.has('q')).toBe(false);
    expect(url.searchParams.has('location')).toBe(false);
    expect(url.searchParams.has('vendor')).toBe(false);
  });

  it('lascia passare gli zeri, che sono valori', async () => {
    // `!value` avrebbe scartato anche questi: vuoto e zero non sono la stessa
    // cosa, e un filtro numerico a zero è una scelta.
    const url = await indirizzoChiamato({ soglia: 0, attivo: false });
    expect(url.searchParams.get('soglia')).toBe('0');
    expect(url.searchParams.get('attivo')).toBe('false');
  });

  it('segnala un errore invece di restituire un file finto', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 422 }));
    await expect(apiDownload('/inventory/export', { format: 'csv' })).rejects.toThrow();
  });
});
