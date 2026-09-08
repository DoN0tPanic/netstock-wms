import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PAGINA_TENDINA, tutteLeVoci, useTendinaPaginata } from './tendina';
import type { Page } from '../types/api';

type Voce = { id: string };
const pagina = (voci: Voce[], total: number, page = 1): Page<Voce> => ({ items: voci, total, page, page_size: PAGINA_TENDINA });
const nVoci = (da: number, quante: number) => Array.from({ length: quante }, (_, i) => ({ id: `id-${da + i}` }));

describe('tendina che carica a pagine', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const primoGiro = async (carica: ReturnType<typeof vi.fn>) => {
    const risultato = renderHook(() => useTendinaPaginata<Voce>(carica));
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    return risultato;
  };

  it('aggiunge la pagina successiva senza ripetere quello che c’è già', async () => {
    const carica = vi.fn()
      .mockResolvedValueOnce(pagina(nVoci(0, 25), 40))
      // Una voce creata nel frattempo fa scivolare le altre di un posto: la
      // pagina 2 riporta l'ultima della pagina 1.
      .mockResolvedValueOnce(pagina([{ id: 'id-24' }, ...nVoci(25, 15)], 41, 2));
    const { result } = await primoGiro(carica);
    expect(result.current.voci).toHaveLength(25);
    expect(result.current.totale).toBe(40);

    await act(async () => { result.current.caricaAltre(); await vi.advanceTimersByTimeAsync(0); });

    expect(carica).toHaveBeenLastCalledWith({ q: undefined, page: 2, page_size: 25 });
    expect(result.current.voci).toHaveLength(40);
    expect(new Set(result.current.voci.map((v) => v.id)).size).toBe(40);
  });

  it('non chiede altro quando ci sono già tutte', async () => {
    const carica = vi.fn().mockResolvedValue(pagina(nVoci(0, 3), 3));
    const { result } = await primoGiro(carica);

    await act(async () => { result.current.caricaAltre(); await vi.advanceTimersByTimeAsync(0); });

    expect(carica).toHaveBeenCalledTimes(1);
  });

  it('scarta la risposta di una ricerca già abbandonata', async () => {
    // Senza questo controllo la risposta lenta della ricerca precedente
    // sovrascriveva quella giusta: nella tendina comparivano le voci di
    // quello che si era appena finito di cancellare.
    let rispondiAllaPrima: (esito: Page<Voce>) => void = () => {};
    const carica = vi.fn()
      .mockImplementationOnce(() => new Promise<Page<Voce>>((resolve) => { rispondiAllaPrima = resolve; }))
      .mockResolvedValueOnce(pagina([{ id: 'giusta' }], 1));
    const { result } = renderHook(() => useTendinaPaginata<Voce>(carica));

    act(() => { result.current.setTesto('cis'); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    act(() => { result.current.setTesto('cisco'); });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(result.current.voci.map((v) => v.id)).toEqual(['giusta']);

    await act(async () => { rispondiAllaPrima(pagina([{ id: 'vecchia' }], 1)); await vi.advanceTimersByTimeAsync(0); });

    expect(result.current.voci.map((v) => v.id)).toEqual(['giusta']);
  });
});

describe('elenchi completi per le tendine native', () => {
  it('continua a chiedere pagine finché non le ha tutte', async () => {
    const carica = vi.fn()
      .mockResolvedValueOnce({ items: nVoci(0, 200), total: 340, page: 1, page_size: 200 })
      .mockResolvedValueOnce({ items: nVoci(200, 140), total: 340, page: 2, page_size: 200 });

    expect(await tutteLeVoci(carica)).toHaveLength(340);
    expect(carica).toHaveBeenCalledTimes(2);
  });

  it('si ferma se il server smette di dare voci, invece di girare a vuoto', async () => {
    // Il totale potrebbe contare righe che la pagina successiva non riporta:
    // senza questa uscita il ciclo non finirebbe mai.
    const carica = vi.fn()
      .mockResolvedValueOnce({ items: nVoci(0, 200), total: 500, page: 1, page_size: 200 })
      .mockResolvedValueOnce({ items: nVoci(200, 30), total: 500, page: 2, page_size: 200 });

    expect(await tutteLeVoci(carica)).toHaveLength(230);
    expect(carica).toHaveBeenCalledTimes(2);
  });
});
