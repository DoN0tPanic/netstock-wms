import { render, screen } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Busy } from './index';

describe('Busy', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('annuncia il lavoro in corso come regione live', () => {
    render(<Busy title="Lettura in corso…">Sto elaborando le pagine.</Busy>);
    const region = screen.getByRole('status');
    expect(region).toHaveTextContent('Lettura in corso…');
    expect(region).toHaveTextContent('Sto elaborando le pagine.');
  });

  it('conta i secondi trascorsi', () => {
    // È il punto della componente: un messaggio fermo su un'attesa di venti
    // secondi è indistinguibile da una pagina bloccata. Il numero che sale è
    // ciò che dice all'operatore che non è successo niente di brutto.
    render(<Busy title="Lettura in corso…"/>);
    expect(screen.getByText('0s')).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(3000); });
    expect(screen.getByText('3s')).toBeInTheDocument();
  });

  it('tiene il contatore fuori dall’annuncio vocale', () => {
    // Con la regione live, un lettore di schermo rileggerebbe la frase intera
    // a ogni secondo.
    render(<Busy title="Lettura in corso…"/>);
    expect(screen.getByText('0s')).toHaveAttribute('aria-hidden', 'true');
  });
});
