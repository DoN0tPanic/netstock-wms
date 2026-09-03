import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CatalogItemModal } from './CatalogItemModal';

vi.mock('../../api', () => ({
  vendorsApi: { list: () => Promise.resolve({ items: [], total: 0, page: 1, page_size: 200 }), create: vi.fn() },
  categoriesApi: { list: () => Promise.resolve({ items: [], total: 0, page: 1, page_size: 200 }), create: vi.fn() },
  catalogApi: { create: vi.fn(), update: vi.fn() },
}));

const tracciamento = () => screen.getByRole<HTMLSelectElement>('combobox', { name: /Tracciamento/ });

describe('CatalogItemModal', () => {
  it('crea articoli serializzati per impostazione predefinita', async () => {
    render(<CatalogItemModal open onClose={vi.fn()} onCreated={vi.fn()}/>);
    expect(await screen.findByDisplayValue(/Serializzato/)).toBeInTheDocument();
  });

  it('parte da "a quantità" quando la bolla non riporta seriali per quella riga', async () => {
    render(<CatalogItemModal open onClose={vi.fn()} onCreated={vi.fn()} prefill={{ part_number: 'CAB-TA-EU', name: 'Cavo', is_serialized: false }}/>);
    await screen.findByDisplayValue('CAB-TA-EU');
    expect(tracciamento().value).toBe('no');
  });

  it('non riscrive il modulo quando il genitore ridisegna', async () => {
    // Regressione: `prefill` è costruito inline da chi chiama, quindi cambia
    // identità a ogni render del genitore. Con l'oggetto fra le dipendenze
    // dell'effetto, un aggiornamento qualunque del genitore — l'interrogazione
    // periodica della lettura in corso, per dirne uno — azzerava quello che
    // l'operatore stava scrivendo.
    const { rerender } = render(
      <CatalogItemModal open onClose={vi.fn()} onCreated={vi.fn()} prefill={{ part_number: 'SW-1', name: 'Switch', is_serialized: true }}/>,
    );
    await screen.findByDisplayValue('SW-1');
    await userEvent.selectOptions(tracciamento(), 'no');
    expect(tracciamento().value).toBe('no');

    // stessi valori, oggetto nuovo: è ciò che accade a ogni render del genitore
    rerender(<CatalogItemModal open onClose={vi.fn()} onCreated={vi.fn()} prefill={{ part_number: 'SW-1', name: 'Switch', is_serialized: true }}/>);
    expect(tracciamento().value).toBe('no');
  });
});
