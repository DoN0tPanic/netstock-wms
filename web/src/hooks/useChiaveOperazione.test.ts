import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useChiaveOperazione } from './useChiaveOperazione';

describe('chiave di un\'operazione di magazzino', () => {
  it('resta la stessa finché l\'operazione non riesce', () => {
    // È il punto: dopo una risposta persa si preme di nuovo, e il server deve
    // riconoscere la stessa operazione, non riceverne una seconda.
    const { result } = renderHook(() => useChiaveOperazione());
    const prima = result.current.corrente();
    expect(result.current.corrente()).toBe(prima);
    expect(result.current.corrente()).toBe(prima);
  });

  it('dopo la riuscita ne comincia una nuova', () => {
    // Due scatole uguali di cavi arrivate una dopo l'altra sono due carichi.
    const { result } = renderHook(() => useChiaveOperazione());
    const prima = result.current.corrente();
    result.current.conclusa();
    const seconda = result.current.corrente();
    expect(seconda).not.toBe(prima);
    expect(seconda).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('sopravvive ai nuovi render del componente', () => {
    const { result, rerender } = renderHook(() => useChiaveOperazione());
    const prima = result.current.corrente();
    rerender();
    expect(result.current.corrente()).toBe(prima);
  });
});
