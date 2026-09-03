import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { authApi } from '../api';
import { ChangePassword } from './ChangePassword';

vi.mock('../api', () => ({
  authApi: {
    changePassword: vi.fn(),
    me: vi.fn(),
  },
}));

const renderPage = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><MemoryRouter><ChangePassword/></MemoryRouter></QueryClientProvider>);
};

describe('ChangePassword', () => {
  beforeEach(() => {
    vi.mocked(authApi.changePassword).mockReset();
    vi.mocked(authApi.me).mockReset();
  });

  it('mantiene il pulsante disabilitato finché tutti i campi non sono validi', async () => {
    const user = userEvent.setup();
    renderPage();
    const button = screen.getByRole('button', { name: 'Salva nuova password' });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText('Password attuale'), 'password-attuale');
    await user.type(screen.getByLabelText('Nuova password'), 'NuovaPassword1!');
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText('Conferma nuova password'), 'NuovaPassword1!');
    expect(button).toBeEnabled();
  });

  it('mostra un errore quando nuova password e conferma non coincidono', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText('Nuova password'), 'NuovaPassword1!');
    await user.type(screen.getByLabelText('Conferma nuova password'), 'PasswordDiversa1!');
    expect(screen.getByText('Le password non corrispondono')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Salva nuova password' })).toBeDisabled();
  });

  it('invia soltanto password attuale e nuova password quando il form è valido', async () => {
    vi.mocked(authApi.changePassword).mockResolvedValue(undefined);
    vi.mocked(authApi.me).mockResolvedValue({ id: 'user-1', username: 'utente', email: null, full_name: 'Utente', role: 'operator', must_change_password: false, permissions: { can_write: true, can_administer: false } });
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText('Password attuale'), 'password-attuale');
    await user.type(screen.getByLabelText('Nuova password'), 'NuovaPassword1!');
    await user.type(screen.getByLabelText('Conferma nuova password'), 'NuovaPassword1!');
    await user.click(screen.getByRole('button', { name: 'Salva nuova password' }));
    expect(authApi.changePassword).toHaveBeenCalledWith({ current_password: 'password-attuale', new_password: 'NuovaPassword1!' });
  });
});
