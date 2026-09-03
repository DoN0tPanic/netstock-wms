import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { DocumentAnalysis, ProposedLine } from '../../types/api';
import { DeliveryNoteProposal } from './DeliveryNoteProposal';

const line = (over: Partial<ProposedLine> = {}): ProposedLine => ({
  position: '1',
  description: 'SWITCH 24 PORTE',
  supplier_code: 'A12BC34',
  part_number: 'SW-STACK-KIT=',
  quantity: '4',
  quantity_ordered: '4',
  catalog_item: null,
  is_serialized: null,
  serials: [],
  secondary_serials: [],
  warnings: [],
  ...over,
});

const analysis = (lines: ProposedLine[], over: Partial<DocumentAnalysis> = {}): DocumentAnalysis => ({
  status: 'done', lines, non_goods: [], unassigned_serials: [],
  model: 'qwen3:4b', duration_ms: 4200, error: null, ...over,
});

const catalogo = { id: 'abc', part_number: 'SW-STACK-KIT=', name: 'Stack module', vendor_code: 'CSC' };

describe('DeliveryNoteProposal', () => {
  it('non lascia scegliere una riga il cui modello non è a catalogo', () => {
    render(<DeliveryNoteProposal analysis={analysis([line()])} onApply={vi.fn()} onCreateItem={vi.fn()}/>);
    expect(screen.getByRole('checkbox')).toBeDisabled();
    expect(screen.getByText(/non è ancora a catalogo/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Usa 0 righe/ })).toBeDisabled();
  });

  it('smette di chiedere di creare il modello appena è a catalogo', () => {
    // Regressione: l'avviso arrivava dal server come testo fisso e restava
    // scritto anche dopo la creazione, accanto al riquadro verde che diceva
    // l'opposto. Ora è derivato da `catalog_item`.
    render(<DeliveryNoteProposal analysis={analysis([line({ catalog_item: catalogo })])} onApply={vi.fn()} onCreateItem={vi.fn()}/>);
    expect(screen.queryByText(/non è ancora a catalogo/)).not.toBeInTheDocument();
    expect(screen.getByText(/A catalogo: SW-STACK-KIT=/)).toBeInTheDocument();
  });

  it('spunta da subito le righe pronte e passa solo quelle', async () => {
    const onApply = vi.fn();
    const pronta = line({ catalog_item: catalogo, serials: ['ABC1234WXYZ'] });
    render(<DeliveryNoteProposal analysis={analysis([pronta, line({ position: '2' })])} onApply={onApply} onCreateItem={vi.fn()}/>);
    await userEvent.click(screen.getByRole('button', { name: /Usa 1 riga/ }));
    expect(onApply).toHaveBeenCalledWith([pronta]);
  });

  it('dichiara i seriali secondari senza contarli come pezzi', () => {
    render(<DeliveryNoteProposal
      analysis={analysis([line({ catalog_item: catalogo, serials: ['A1'], secondary_serials: ['B1'] })])}
      onApply={vi.fn()} onCreateItem={vi.fn()}/>);
    expect(screen.getByText(/non vengono caricati come pezzi/)).toBeInTheDocument();
  });

  it('dice cosa fare quando non ha riconosciuto nessuna riga', () => {
    render(<DeliveryNoteProposal analysis={analysis([])} onApply={vi.fn()} onCreateItem={vi.fn()}/>);
    expect(screen.getByText(/Nessuna riga riconosciuta/)).toBeInTheDocument();
  });
});
