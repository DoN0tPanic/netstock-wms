import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ session: { full_name: 'Chi Guarda', role: 'admin' }, logout: vi.fn() }),
}));
vi.mock('./GlobalSearch', () => ({ GlobalSearch: () => <div/> }));

const { Layout } = await import('./Layout');

const monta = () => render(<MemoryRouter><Layout/></MemoryRouter>);

beforeEach(() => { localStorage.clear(); });

describe('Layout', () => {
  it('riduce la barra alle sole icone e se lo ricorda', async () => {
    const user = userEvent.setup();
    const { unmount } = monta();

    // Estesa: le voci hanno il loro nome scritto.
    expect(screen.getByRole('link', { name: 'Magazzino' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Riduci la barra' }));

    // Ridotta il nome resta come titolo — l'icona da sola costringerebbe a
    // indovinare — ma non occupa più spazio a schermo.
    const voce = screen.getByRole('link', { name: 'Magazzino' });
    expect(voce).toHaveAttribute('title', 'Magazzino');
    expect(voce.querySelector('span')).toHaveClass('lg:hidden');

    // La preferenza è di chi guarda: al ritorno la barra è come l'aveva
    // lasciata, senza passare dal database.
    unmount();
    monta();
    expect(screen.getByRole('button', { name: 'Espandi la barra' })).toBeInTheDocument();
  });

  it('il contenuto si allarga quando la barra si stringe', async () => {
    const user = userEvent.setup();
    monta();
    const contenuto = document.querySelector('main')!;
    expect(contenuto.className).toContain('lg:ml-64');

    await user.click(screen.getByRole('button', { name: 'Riduci la barra' }));

    // È tutto il punto della richiesta: lo spazio lasciato dalla barra deve
    // andare al contenuto, non restare margine vuoto.
    expect(contenuto.className).toContain('lg:ml-16');
  });

  it('non si rompe se il browser non lascia memorizzare le preferenze', () => {
    // Finestra anonima, o archiviazione bloccata: l'accesso stesso solleva.
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('bloccato'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('bloccato'); });
    monta();
    expect(screen.getByRole('link', { name: 'Dashboard' })).toBeInTheDocument();
    vi.restoreAllMocks();
  });
});
