import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { CatalogItem } from '../../types/api';
import { ReceiveLineCard, newPiece, type ReceiveLine } from './ReceiveLineCard';

const modello = (over: Partial<CatalogItem> = {}): CatalogItem => ({
  id: 'item-1', part_number: 'C9200-STACK-KIT=', name: 'STACK MODULE',
  vendor_id: 'v', category_id: 'c', is_serialized: true, serial_pattern: null,
  reorder_point: null, is_active: true, ...over,
} as CatalogItem);

const riga = (over: Partial<ReceiveLine> = {}): ReceiveLine => ({
  key: 'r1', item: modello(), expected: 2, condition: 'new',
  pieces: [newPiece('ABC1234WXYZ', 'loc'), newPiece('ABC1234WXZ0', 'loc')],
  quantity: 2, ...over,
});

function montaggio(line: ReceiveLine, onChange = vi.fn()) {
  render(<ReceiveLineCard
    line={line} index={0} removable onRemove={vi.fn()} onChange={onChange} onSelectItem={vi.fn()}
    catalogQuery="" onCatalogQuery={vi.fn()} catalogOptions={[]} catalogSearching={false}
    locations={[]} defaultLocationId="loc" templates={[]} onExtract={vi.fn()} onApplyExtracted={vi.fn()}/>);
  return onChange;
}

describe('ReceiveLineCard', () => {
  it('mostra il modello come intestazione, non come campo da scegliere', () => {
    montaggio(riga());
    expect(screen.getByRole('heading', { name: /C9200-STACK-KIT=/ })).toBeInTheDocument();
    expect(screen.queryByLabelText('Modello')).not.toBeInTheDocument();
  });

  it('elenca i seriali numerati e modificabili', async () => {
    const onChange = montaggio(riga());
    expect(screen.getByText('1.')).toBeInTheDocument();
    expect(screen.getByText('2.')).toBeInTheDocument();
    const primo = screen.getByLabelText('Seriale 1');
    expect(primo).toHaveValue('ABC1234WXYZ');
    await userEvent.type(primo, 'X');
    expect(onChange).toHaveBeenCalled();
    const change = onChange.mock.calls[0]?.[0] as { pieces: Array<{ serial_number: string }> };
    expect(change.pieces[0]?.serial_number).toBe('ABC1234WXYZX');
  });

  it('lascia correggere un carattere in mezzo al seriale', async () => {
    // Regressione: il valore veniva trasformato in maiuscolo a ogni tasto, il
    // che costringe React a riscrivere il campo e manda il cursore in fondo.
    // Correggere un carattere in mezzo — il gesto per cui il campo esiste —
    // accodava il testo invece di sostituirlo. Serve un contenitore che tenga
    // davvero lo stato: con un `onChange` finto la riga non cambia mai e il
    // test non direbbe niente.
    function Contenitore() {
      const [line, setLine] = useState(riga({ pieces: [newPiece('ABC1234WXYZ', 'loc')] }));
      return <ReceiveLineCard
        line={line} index={0} removable onRemove={vi.fn()}
        onChange={(change) => setLine((old) => ({ ...old, ...change }))} onSelectItem={vi.fn()}
        catalogQuery="" onCatalogQuery={vi.fn()} catalogOptions={[]} catalogSearching={false}
        locations={[]} defaultLocationId="loc" templates={[]} onExtract={vi.fn()} onApplyExtracted={vi.fn()}/>;
    }
    render(<Contenitore/>);
    const campo = screen.getByLabelText<HTMLInputElement>('Seriale 1');

    // sostituzione completa
    await userEvent.clear(campo);
    await userEvent.type(campo, 'zzq4471ak19');
    expect(campo.value).toBe('zzq4471ak19');

    // correzione di un carattere in mezzo: il cursore resta dov'è
    campo.setSelectionRange(3, 4);
    await userEvent.type(campo, 'X', { initialSelectionStart: 3, initialSelectionEnd: 4 });
    expect(campo.value).toBe('zzqX471ak19');

    // uscendo dal campo il valore prende la sua forma definitiva
    await userEvent.tab();
    expect(campo.value).toBe('ZZQX471AK19');
  });

  it('segnala un seriale ripetuto nella stessa riga', () => {
    montaggio(riga({ pieces: [newPiece('AAA1111BBBB', 'loc'), newPiece('AAA1111BBBB', 'loc')] }));
    expect(screen.getAllByText('Già presente in questa riga.')).toHaveLength(2);
  });

  it('non fa digitare i pezzi arrivati su una riga serializzata: li conta', () => {
    // Sarebbe un numero che il salvataggio ignora — quello che viene registrato
    // è la lista dei seriali.
    montaggio(riga());
    // La label avvolge il campo, quindi il testo accessibile include anche il
    // suggerimento sotto: si cerca per espressione regolare, non esatta.
    expect(screen.queryByLabelText(/Pezzi arrivati/)).not.toBeInTheDocument();
    expect(screen.getByText('Pezzi arrivati')).toBeInTheDocument();
  });

  it('dice cosa comporta registrare meno pezzi di quelli dichiarati', () => {
    montaggio(riga({ expected: 24 }));
    expect(screen.getByText(/resta aperta per i 22 mancanti/)).toBeInTheDocument();
  });

  it('tace quando il conto torna', () => {
    montaggio(riga());
    expect(screen.queryByText(/resta aperta/)).not.toBeInTheDocument();
  });

  it('su un articolo a quantità chiede il numero e non i seriali', () => {
    montaggio(riga({ item: { ...modello(), is_serialized: false }, pieces: [], quantity: 9, expected: 9 }));
    expect(screen.getByLabelText(/Pezzi arrivati/)).toHaveValue(9);
    expect(screen.queryByRole('heading', { name: 'Seriali' })).not.toBeInTheDocument();
  });
});
