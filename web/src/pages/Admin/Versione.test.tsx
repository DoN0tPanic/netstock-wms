import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Versione } from '../../types/api';

const leggi = vi.fn<() => Promise<Versione>>();
vi.mock('../../api', () => ({ versioneApi: { leggi: () => leggi() } }));

const { VersioneAdmin } = await import('./Versione');

const versione = (altro: Partial<Versione> = {}): Versione => ({
  commit: '7faa702', data_commit: '2026-09-27T11:55:00+02:00', costruita: '2026-09-28T07:00:00Z',
  avviata: '2026-09-28T07:01:00Z', schema_attuale: '0010', schema_previsto: '0010',
  python: '3.12.14', postgresql: '16.15', ...altro,
});
const monta = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><VersioneAdmin/></QueryClientProvider>);
};

describe('la versione nelle Impostazioni', () => {
  beforeEach(() => leggi.mockReset());
  afterEach(() => vi.unstubAllEnvs());

  it('mostra commit, schema aggiornato e componenti, senza avvisi', async () => {
    vi.stubEnv('VITE_COMMIT', '7faa702');
    leggi.mockResolvedValue(versione());
    monta();
    expect(await screen.findByText('7faa702')).toBeInTheDocument();
    expect(screen.getByText(/aggiornato/)).toBeInTheDocument();
    expect(screen.getByText(/Python 3\.12\.14 · PostgreSQL 16\.15/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it("avvisa se l'interfaccia aperta nel browser viene da un altro commit", async () => {
    vi.stubEnv('VITE_COMMIT', '1bbfd75');
    leggi.mockResolvedValue(versione());
    monta();
    expect(await screen.findByRole('alert')).toHaveTextContent(/ricarica la pagina/);
  });

  it('avvisa se lo schema non è quello che il codice si aspetta', async () => {
    leggi.mockResolvedValue(versione({ schema_attuale: '0009' }));
    monta();
    expect(await screen.findByRole('alert')).toHaveTextContent(/le migrazioni non sono passate/);
  });

  it("senza il file di build dice che il commit è sconosciuto, invece d'inventarlo", async () => {
    leggi.mockResolvedValue(versione({ commit: null, data_commit: null, costruita: null }));
    monta();
    expect(await screen.findByText('sconosciuto')).toBeInTheDocument();
    expect(screen.getByText(/non è stata costruita da una copia git/)).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
