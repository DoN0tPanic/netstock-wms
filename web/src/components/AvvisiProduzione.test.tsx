import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AvvisiProduzione as Risposta, Avviso } from '../types/api';

const leggi = vi.fn<() => Promise<Risposta>>();
let amministratore = true;
vi.mock('../api', () => ({ avvisiApi: { leggi: () => leggi() } }));
vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ session: { permissions: { can_administer: amministratore, can_write: true } } }),
}));

const { AvvisiProduzione } = await import('./AvvisiProduzione');

const avviso = (codice: string, gravita: Avviso['gravita'] = 'critico'): Avviso =>
  ({ codice, gravita, titolo: `Titolo di ${codice}`, dettaglio: `Cosa fare per ${codice}` });
const risposta = (avvisi: Avviso[], scartoMinuti = 0): Risposta =>
  ({ ora_server: new Date(Date.now() + scartoMinuti * 60_000).toISOString(), avvisi });
const monta = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><AvvisiProduzione/></MemoryRouter></QueryClientProvider>);
};

describe('gli avvisi che proteggono la produzione', () => {
  beforeEach(() => { leggi.mockReset(); amministratore = true; localStorage.clear(); });

  it("l'amministratore li vede, con cosa fare", async () => {
    leggi.mockResolvedValue(risposta([avviso('backup_vuoto'), avviso('disco_quasi_pieno', 'attenzione')]));
    monta();
    const riquadro = await screen.findByRole('alert');
    expect(riquadro).toHaveTextContent('2 problemi da guardare');
    expect(riquadro).toHaveTextContent('Titolo di backup_vuoto');
    expect(riquadro).toHaveTextContent('Cosa fare per disco_quasi_pieno');
  });

  it('chi non è amministratore non li vede, e non li chiede nemmeno', async () => {
    amministratore = false;
    leggi.mockResolvedValue(risposta([avviso('backup_vuoto')]));
    monta();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(leggi).not.toHaveBeenCalled();
  });

  it("senza problemi non compare niente", async () => {
    leggi.mockResolvedValue(risposta([]));
    monta();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it("l'orologio del server avanti di due ore diventa un avviso", async () => {
    leggi.mockResolvedValue(risposta([], 120));
    monta();
    expect(await screen.findByRole('alert')).toHaveTextContent("L'ora del server è avanti di 2 ore");
  });

  it('nascosto per un giorno, ricompare se arriva un problema nuovo', async () => {
    leggi.mockResolvedValue(risposta([avviso('backup_solo_locale', 'attenzione')]));
    const { unmount } = monta();
    await userEvent.click(await screen.findByRole('button', { name: 'Nascondi per un giorno' }));
    expect(screen.queryByRole('alert')).toBeNull();
    unmount();

    monta();
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole('alert')).toBeNull();
    // Lo stesso problema resta nascosto; uno nuovo lo fa ricomparire.
    leggi.mockResolvedValue(risposta([avviso('backup_solo_locale', 'attenzione'), avviso('backup_fallito')]));
    monta();
    expect(await screen.findByRole('alert')).toHaveTextContent('Titolo di backup_fallito');
  });
});
