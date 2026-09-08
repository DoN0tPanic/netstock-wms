import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Combobox } from './index';

/** In jsdom ogni misura è zero, quindi il pannello sembra sempre già in fondo.
 *  Queste due dicono quanto è alto e quanto ne è visibile. */
const misura = (altezza: number, visibile: number) => {
  const proprieta = ['scrollHeight', 'clientHeight'] as const;
  const originali = proprieta.map((nome) => Object.getOwnPropertyDescriptor(HTMLElement.prototype, nome));
  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable: true, get: () => altezza });
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => visibile });
  return () => proprieta.forEach((nome, indice) => {
    const originale = originali[indice];
    if (originale) Object.defineProperty(HTMLElement.prototype, nome, originale);
    else delete (HTMLElement.prototype as unknown as Record<string, unknown>)[nome];
  });
};

const voci = (quante: number) => Array.from({ length: quante }, (_, indice) => ({ id: `id-${indice}`, label: `Modello ${indice}` }));
let ripristina = () => {};
afterEach(() => ripristina());

describe('Combobox', () => {
  it('dice quante voci si stanno vedendo su quante ce ne sono', async () => {
    // La domanda che la vecchia tendina lasciava aperta: quelle otto erano
    // tutte? le ultime usate? le prime otto di trecento? Ora c'è scritto.
    ripristina = misura(900, 288);
    render(<Combobox query="" onQueryChange={vi.fn()} options={voci(25)} total={320} onSelect={vi.fn()} onLoadMore={vi.fn()}/>);

    await userEvent.click(screen.getByRole('textbox'));

    expect(screen.getByText(/25 di 320/)).toBeInTheDocument();
  });

  it('quando le voci sono tutte lì non promette che ce ne siano altre', async () => {
    ripristina = misura(900, 288);
    render(<Combobox query="" onQueryChange={vi.fn()} options={voci(3)} total={3} onSelect={vi.fn()} onLoadMore={vi.fn()}/>);

    await userEvent.click(screen.getByRole('textbox'));

    expect(screen.getByText('3 voci in tutto')).toBeInTheDocument();
    expect(screen.queryByText(/scorri/)).not.toBeInTheDocument();
  });

  it('scorrendo fino in fondo chiede le successive', async () => {
    ripristina = misura(900, 288);
    const altre = vi.fn();
    render(<Combobox query="" onQueryChange={vi.fn()} options={voci(25)} total={320} onSelect={vi.fn()} onLoadMore={altre}/>);
    await userEvent.click(screen.getByRole('textbox'));
    expect(altre).not.toHaveBeenCalled();

    const lista = screen.getByRole('listbox');
    Object.defineProperty(lista, 'scrollTop', { configurable: true, value: 700 });
    fireEvent.scroll(lista);

    expect(altre).toHaveBeenCalled();
  });

  it('se il pannello non arriva a riempirsi le chiede da solo', async () => {
    // Senza barra da scorrere non ci sarebbe nessun gesto con cui chiederle,
    // e le voci successive non arriverebbero mai.
    ripristina = misura(200, 288);
    const altre = vi.fn();
    render(<Combobox query="" onQueryChange={vi.fn()} options={voci(4)} total={40} onSelect={vi.fn()} onLoadMore={altre}/>);

    await userEvent.click(screen.getByRole('textbox'));

    expect(altre).toHaveBeenCalled();
  });

  it('la freccia giù in fondo alla lista chiede le successive', async () => {
    ripristina = misura(900, 288);
    const altre = vi.fn();
    render(<Combobox query="" onQueryChange={vi.fn()} options={voci(2)} total={40} onSelect={vi.fn()} onLoadMore={altre}/>);
    const campo = screen.getByRole('textbox');
    await userEvent.click(campo);

    await userEvent.keyboard('{ArrowDown}');
    expect(altre).not.toHaveBeenCalled();
    await userEvent.keyboard('{ArrowDown}');

    expect(altre).toHaveBeenCalled();
  });
});
