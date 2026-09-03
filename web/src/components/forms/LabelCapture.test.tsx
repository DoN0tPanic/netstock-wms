import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type React from 'react';
import { LabelCapture } from './LabelCapture';

const estrai = vi.fn();
vi.mock('../../api', () => ({ extractionApi: { extract: (...args: unknown[]): Promise<unknown> => estrai(...args) as Promise<unknown> } }));
vi.mock('../scanner/BarcodeCamera', () => ({
  BarcodeCamera: ({ onDetected }: { onDetected: (v: string) => void }) =>
    <button type="button" onClick={() => onDetected('zzo0004test')}>codice-letto</button>,
}));
vi.mock('../scanner/PhotoExtract', () => ({
  EXTRACTION_FILE_ACCEPT: 'image/*',
  prepareExtractionImage: (file: File) => Promise.resolve(file),
}));

const etichetta = (over: Record<string, unknown> = {}) => ({
  fields: {
    part_number: { value: 'C9200L-24P-4G-E' },
    serial_number: { value: 'ZZO0002TEST' },
    mac_address: { value: '00:11:22:33:44:55' },
  },
  matched_catalog_item: { id: 'item-1', part_number: 'C9200L-24P-4G-E', name: 'Catalyst 9200L' },
  ...over,
});

type Props = Partial<React.ComponentProps<typeof LabelCapture>>;
const monta = (props: Props = {}) => render(<LabelCapture
  templates={[]} catalogQuery="" onCatalogQuery={vi.fn()} catalogOptions={[]} catalogSearching={false}
  onAdd={vi.fn()} onCreateItem={vi.fn()} {...props}/>);

const scatta = async () => {
  const file = new File(['x'], 'etichetta.png', { type: 'image/png' });
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.upload(input, file);
};

const catalogo = [{ id: 'item-1', part_number: 'C9200L-24P-4G-E', name: 'Catalyst 9200L' }] as never;
const inquadra = async () => {
  await userEvent.click(screen.getByRole('button', { name: /Inquadra il barcode/ }));
  await userEvent.click(await screen.findByRole('button', { name: 'codice-letto' }));
};

describe('LabelCapture', () => {
  beforeEach(() => { estrai.mockReset(); });

  it('propone quello che ha letto, senza aggiungerlo da solo', async () => {
    estrai.mockResolvedValue(etichetta());
    const onAdd = vi.fn();
    monta({ onAdd });
    await scatta();
    expect(await screen.findByDisplayValue('ZZO0002TEST')).toBeInTheDocument();
    expect(screen.getByDisplayValue('00:11:22:33:44:55')).toBeInTheDocument();
    expect(screen.getByText(/A catalogo: Catalyst 9200L/)).toBeInTheDocument();
    expect(onAdd).not.toHaveBeenCalled();
  });

  it('lascia correggere il seriale prima di accettarlo', async () => {
    estrai.mockResolvedValue(etichetta());
    const onAdd = vi.fn().mockResolvedValue({ ok: true });
    monta({ onAdd });
    await scatta();
    const campo = await screen.findByDisplayValue('ZZO0002TEST');
    await userEvent.clear(campo);
    await userEvent.type(campo, 'ZZO0003TEST');
    await userEvent.click(screen.getByRole('button', { name: /Aggiungi e scatta/ }));
    await waitFor(() => expect(onAdd).toHaveBeenCalled());
    expect(onAdd.mock.calls[0]?.[0]).toMatchObject({ serial_number: 'ZZO0003TEST' });
  });

  it('quando il modello non è a catalogo offre di crearlo, non di aggiungere', async () => {
    estrai.mockResolvedValue(etichetta({ matched_catalog_item: null }));
    monta();
    await scatta();
    expect(await screen.findByRole('button', { name: /Crea l'articolo a catalogo/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Aggiungi e scatta/ })).not.toBeInTheDocument();
  });

  it('mostra il motivo quando l’aggiunta viene rifiutata, e non conta il pezzo', async () => {
    estrai.mockResolvedValue(etichetta());
    monta({ onAdd: vi.fn().mockResolvedValue({ ok: false, motivo: 'Seriale già presente.' }) });
    await scatta();
    await userEvent.click(await screen.findByRole('button', { name: /Aggiungi e scatta/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Seriale già presente.');
    expect(screen.queryByText(/Finora ne hai aggiunti/)).not.toBeInTheDocument();
  });

  it('spiega perché non si può ancora scattare', () => {
    monta({ disabled: true, disabledReason: "Scegli prima l'ubicazione." });
    expect(screen.getByText("Scegli prima l'ubicazione.")).toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeDisabled();
  });

  it('col barcode chiede il modello, che il seriale da solo non dice', async () => {
    monta({ catalogOptions: catalogo });
    await inquadra();
    expect(await screen.findByDisplayValue('ZZO0004TEST')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Aggiungi e scatta/ })).not.toBeInTheDocument();
  });

  it('tiene il modello per i pezzi successivi', async () => {
    // È il caso più comune: venti apparati identici. Si sceglie una volta, poi
    // si scansiona e basta.
    const onAdd = vi.fn().mockResolvedValue({ ok: true });
    monta({ onAdd, catalogOptions: catalogo });
    await inquadra();
    // le opzioni della ricerca compaiono solo col campo a fuoco
    await userEvent.click(screen.getByPlaceholderText(/Cerca per part number/));
    await userEvent.click(await screen.findByRole('option', { name: /C9200L-24P-4G-E/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Aggiungi e scatta/ }));
    await waitFor(() => expect(onAdd).toHaveBeenCalled());

    await userEvent.click(await screen.findByRole('button', { name: 'codice-letto' }));
    expect(await screen.findByRole('button', { name: /Aggiungi e scatta/ })).toBeEnabled();
    expect(screen.getByText(/A catalogo: Catalyst 9200L/)).toBeInTheDocument();
  });

  it('rilegge col barcode un seriale letto male dalla foto', async () => {
    estrai.mockResolvedValue(etichetta());
    monta();
    await scatta();
    await userEvent.click(await screen.findByRole('button', { name: /Rileggi/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'codice-letto' }));
    expect(await screen.findByDisplayValue('ZZO0004TEST')).toBeInTheDocument();
  });
});
