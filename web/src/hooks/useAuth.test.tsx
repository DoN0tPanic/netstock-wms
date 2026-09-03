import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

type Sessione = { id: string; username: string; full_name: string; email: string | null; role: string; must_change_password: boolean; permissions: { can_write: boolean; can_administer: boolean } };
const me = vi.fn<() => Promise<Sessione>>();
const logout = vi.fn<() => Promise<void>>();
vi.mock('../api', () => ({ authApi: { me: () => me(), login: vi.fn(), logout: () => logout() } }));

const { AuthProvider, useAuth } = await import('./useAuth');

function Spia() {
  const { session, logout: esci } = useAuth();
  return <div>
    <span data-testid="chi">{session?.username ?? 'nessuno'}</span>
    <button onClick={() => void esci()}>Esci</button>
  </div>;
}

describe('uscita', () => {
  it('lascia l\'interfaccia senza sessione, non solo il server', async () => {
    // Il difetto: `setQueryData(chiave, undefined)` in TanStack Query vuol
    // dire «non cambiare nulla». La sessione sul server veniva chiusa e
    // l'interfaccia restava dov'era, con l'utente ancora in alto a destra e
    // ogni chiamata successiva a 401.
    me.mockResolvedValue({ id: '1', username: 'admin', full_name: 'Amministratore', email: null, role: 'admin', must_change_password: false, permissions: { can_write: true, can_administer: true } });
    logout.mockResolvedValue(undefined);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const user = userEvent.setup();
    render(<QueryClientProvider client={client}><AuthProvider><Spia/></AuthProvider></QueryClientProvider>);

    await waitFor(() => expect(screen.getByTestId('chi')).toHaveTextContent('admin'));
    me.mockRejectedValue(new Error('401'));
    await user.click(screen.getByRole('button', { name: 'Esci' }));

    await waitFor(() => expect(screen.getByTestId('chi')).toHaveTextContent('nessuno'));
  });
});
