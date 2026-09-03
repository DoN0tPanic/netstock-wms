import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '../../components/ui';
import type { User } from '../../types/api';

/** Un utente eliminato che il registro cita: si può solo ripristinare. */
const chiuso = (): User => ({
  id: 'u2', username: 'chi-ha-firmato', email: null, full_name: 'Chi Ha Firmato',
  role: 'operator', auth_provider: 'local', is_active: false, must_change_password: true,
  last_login_at: null, deleted_at: '2026-09-01T10:00:00Z', can_purge: false,
  created_at: '2026-08-01T10:00:00Z', updated_at: '2026-09-01T10:00:00Z',
});
/** Un utente eliminato che non ha lasciato tracce: si può togliere davvero. */
const senzaStoria = (): User => ({ ...chiuso(), id: 'u3', username: 'mai-usato', full_name: 'Mai Usato', can_purge: true });
const attivo = (): User => ({ ...chiuso(), id: 'u1', username: 'in-servizio', full_name: 'In Servizio', is_active: true, deleted_at: null, can_purge: false });

type Elenco = { items: User[]; total: number; page: number; page_size: number };
type Esito = { removed: boolean; username: string; traces: Record<string, number>; purgeable: boolean };
const elenco = vi.fn<(query: { include_deleted?: boolean }) => Promise<Elenco>>();
const remove = vi.fn<(id: string) => Promise<Esito>>();
const purge = vi.fn<(id: string) => Promise<Esito>>();
vi.mock('../../api', () => ({
  usersApi: {
    list: (query: { include_deleted?: boolean }) => elenco(query),
    remove: (id: string) => remove(id),
    purge: (id: string) => purge(id),
    create: vi.fn(), update: vi.fn(), resetPassword: vi.fn(), restore: vi.fn(),
  },
  adminApi: {}, categoriesApi: {}, extractionApi: {}, vendorsApi: {},
}));

const { UsersAdmin } = await import('./index');

const pagina = (items: User[]) => ({ items, total: items.length, page: 1, page_size: 200 });
const monta = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><ToastProvider><UsersAdmin/></ToastProvider></QueryClientProvider>);
};

beforeEach(() => {
  elenco.mockReset(); remove.mockReset(); purge.mockReset();
  elenco.mockImplementation(({ include_deleted }: { include_deleted?: boolean }) =>
    Promise.resolve(pagina(include_deleted ? [attivo(), chiuso(), senzaStoria()] : [attivo()])));
});

describe('UsersAdmin', () => {
  it('dopo l\'eliminazione mostra l\'account chiuso invece di farlo sparire', async () => {
    // Il difetto: la riga usciva dall\'elenco e non tornava nemmeno spuntando
    // «Mostra anche gli eliminati», così l\'eliminazione sembrava fallita.
    remove.mockResolvedValue({ removed: false, username: 'in-servizio', traces: {}, purgeable: true });
    const user = userEvent.setup();
    monta();

    await user.click(await screen.findByRole('button', { name: 'Elimina' }));
    // Il secondo «Elimina» è quello della conferma: la finestra sta in fondo al DOM.
    await user.click(screen.getAllByRole('button', { name: 'Elimina' }).at(-1)!);

    await waitFor(() => expect(remove).toHaveBeenCalledWith('u1'));
    expect(screen.getByLabelText('Mostra anche gli eliminati')).toBeChecked();
    expect(await screen.findByText('chi-ha-firmato')).toBeInTheDocument();
  });

  it('offre la rimozione definitiva solo a chi non ha firmato niente', async () => {
    const user = userEvent.setup();
    monta();
    await user.click(await screen.findByLabelText('Mostra anche gli eliminati'));

    await screen.findByText('mai-usato');
    expect(screen.getAllByRole('button', { name: 'Elimina definitivamente' })).toHaveLength(1);
    // Per l\'altro non c\'è un pulsante spento senza spiegazione, ma il motivo.
    expect(screen.getByText(/Resta nel registro/)).toBeInTheDocument();
  });

  it('chiede una seconda conferma prima di togliere dal database', async () => {
    purge.mockResolvedValue({ removed: true, username: 'mai-usato', traces: {}, purgeable: false });
    const user = userEvent.setup();
    monta();
    await user.click(await screen.findByLabelText('Mostra anche gli eliminati'));
    await user.click(await screen.findByRole('button', { name: 'Elimina definitivamente' }));

    expect(purge).not.toHaveBeenCalled();
    expect(screen.getByText(/non si annulla/)).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: 'Elimina definitivamente' }).at(-1)!);
    await waitFor(() => expect(purge).toHaveBeenCalledWith('u3'));
  });
});
