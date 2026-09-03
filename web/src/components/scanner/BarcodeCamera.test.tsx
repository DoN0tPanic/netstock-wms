import { render, screen } from '@testing-library/react';
import { act } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { EsitoLettura } from './BarcodeCamera';

// La fotocamera vera non esiste in un test, ma il comportamento che conta non è
// la decodifica: è cosa succede *dopo* un codice letto. Il finto lettore
// consegna il callback, e il test decide cosa "inquadrare" e quando.
let consegna: ((result: { getText: () => string } | null, error?: Error) => void) | null = null;
const reset = vi.fn();
vi.mock('@zxing/library', () => ({
  NotFoundException: class NotFoundException extends Error {},
  BarcodeFormat: { CODE_128: 1, CODE_39: 2, CODE_93: 3, ITF: 4, DATA_MATRIX: 5, QR_CODE: 6, EAN_13: 7, UPC_A: 8 },
  DecodeHintType: { POSSIBLE_FORMATS: 2 },
  BrowserMultiFormatReader: class {
    decodeFromConstraints(_c: unknown, _v: unknown, callback: typeof consegna) { consegna = callback; return Promise.resolve(); }
    reset() { reset(); }
  },
}));

const { BarcodeCamera } = await import('./BarcodeCamera');

const inquadra = async (valore: string) => {
  await act(async () => { consegna?.({ getText: () => valore }); await Promise.resolve(); });
};

beforeEach(() => {
  consegna = null;
  reset.mockClear();
  Object.defineProperty(navigator, 'mediaDevices', {
    value: { enumerateDevices: () => Promise.resolve([]) }, configurable: true,
  });
});

describe('BarcodeCamera', () => {
  it('legge un codice dopo l\'altro senza chiudersi', async () => {
    const onDetected = vi.fn(() => 'valid' as EsitoLettura);
    const onClose = vi.fn();
    render(<BarcodeCamera continuo onDetected={onDetected} onClose={onClose} progresso={{ letti: 0, attesi: 24 }}/>);

    await inquadra('ZZO0000TEST');
    await inquadra('ZZO0001TEST');

    expect(onDetected).toHaveBeenCalledTimes(2);
    // Chiudere a ogni pezzo è precisamente ciò che rendeva lenta la
    // scansione di ventiquattro apparati.
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText('ZZO0000TEST')).toBeInTheDocument();
    expect(screen.getByText('ZZO0001TEST')).toBeInTheDocument();
  });

  it('non conta venti volte lo stesso codice tenuto inquadrato', async () => {
    // Il lettore rilegge lo stesso barcode a ogni fotogramma finché resta
    // davanti all'obiettivo: senza la finestra di silenzio, appoggiare il
    // telefono su un'etichetta genererebbe decine di letture identiche.
    const onDetected = vi.fn(() => 'valid' as EsitoLettura);
    render(<BarcodeCamera continuo onDetected={onDetected} onClose={() => {}}/>);

    await inquadra('ZZO0000TEST');
    await inquadra('ZZO0000TEST');
    await inquadra('ZZO0000TEST');

    expect(onDetected).toHaveBeenCalledTimes(1);
  });

  it('mostra il responso del genitore sopra l\'immagine', async () => {
    // Con la fotocamera aperta il modulo dietro non si vede: se il seriale è
    // un doppione, l'unico posto dove dirlo è qui.
    render(<BarcodeCamera continuo onDetected={() => 'duplicate'} onClose={() => {}}/>);
    await inquadra('ZZO0000TEST');
    expect(screen.getByText(/già letto/)).toBeInTheDocument();
  });

  it('mostra a che punto è la riga', async () => {
    render(<BarcodeCamera continuo onDetected={() => 'valid'} onClose={() => {}} progresso={{ letti: 12, attesi: 24 }}/>);
    await act(async () => { await Promise.resolve(); }); // lascia concludere l'avvio
    expect(screen.getByText('12 / 24')).toBeInTheDocument();
  });

  it('in lettura singola non elenca nulla e si chiude a mano', async () => {
    const onDetected = vi.fn();
    render(<BarcodeCamera onDetected={onDetected} onClose={() => {}}/>);
    await inquadra('ZZO0000TEST');
    expect(onDetected).toHaveBeenCalledWith('ZZO0000TEST');
    expect(screen.queryByText('ZZO0000TEST')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Chiudi fotocamera' })).toBeInTheDocument();
  });
});
