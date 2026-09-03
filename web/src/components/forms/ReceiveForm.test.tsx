import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const pagina = <T,>(items: T[]) => Promise.resolve({ items, total: items.length, page: 1, page_size: 50 });
vi.mock('../../api', () => ({
  deliveryNotesApi: { list: () => pagina([]) },
  suppliersApi: { list: () => pagina([]) },
  locationsApi: { list: () => pagina([]) },
  catalogApi: { list: () => pagina([]) },
  movementsApi: {},
  extractionApi: { templates: { list: () => Promise.resolve([]) } },
}));

const { ReceiveForm } = await import('./ReceiveForm');

/** Larghezza dello schermo, che è l'unica cosa che decide la forma di questa
 *  pagina: una schermata per volta sul telefono, tutto insieme sulla scrivania. */
const schermo = (stretto: boolean) => {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: stretto, media: query,
    addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, onchange: null,
    dispatchEvent: () => false,
  }));
};

beforeEach(() => { vi.unstubAllGlobals(); });

describe('ReceiveForm su telefono', () => {
  it('mostra un passo alla volta', async () => {
    schermo(true);
    render(<ReceiveForm onSuccess={() => {}}/>);
    expect(await screen.findByText('1. Bolla')).toBeInTheDocument();
    // Le sezioni successive esistono nel modulo ma non a schermo: è tutta la
    // differenza fra una pagina lunga tre schermate e un percorso.
    expect(screen.queryByText('3. Righe e acquisizione')).not.toBeInTheDocument();
  });

  it('non lascia avanzare finché non si è scelta una bolla, e dice perché', async () => {
    schermo(true);
    const user = userEvent.setup();
    render(<ReceiveForm onSuccess={() => {}}/>);

    const avanti = await screen.findByRole('button', { name: /Avanti/ });
    expect(avanti).toBeDisabled();
    // Un pulsante spento che non dice cosa manca è un vicolo cieco.
    expect(screen.getByText(/Scegli una bolla/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Bolla'), 'none');
    expect(avanti).toBeEnabled();

    await user.click(avanti);
    expect(screen.getByText('2. Ubicazione predefinita')).toBeInTheDocument();
    expect(screen.queryByText('1. Bolla')).not.toBeInTheDocument();
  });

  it('permette di tornare su un passo già fatto', async () => {
    schermo(true);
    const user = userEvent.setup();
    render(<ReceiveForm onSuccess={() => {}}/>);
    await user.selectOptions(await screen.findByLabelText('Bolla'), 'none');
    await user.click(screen.getByRole('button', { name: /Avanti/ }));

    await user.click(screen.getByRole('button', { name: 'Passo 1: Bolla' }));
    expect(screen.getByText('1. Bolla')).toBeInTheDocument();
  });
});

describe('ReceiveForm su scrivania', () => {
  it('resta la pagina unica di sempre', async () => {
    schermo(false);
    const user = userEvent.setup();
    render(<ReceiveForm onSuccess={() => {}}/>);
    await user.selectOptions(await screen.findByLabelText('Bolla'), 'none');

    expect(screen.getByText('1. Bolla')).toBeInTheDocument();
    expect(screen.getByText('2. Ubicazione predefinita')).toBeInTheDocument();
    expect(screen.getByText('3. Righe e acquisizione')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Avanti/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Registra ricezione' })).toBeInTheDocument();
  });
});
