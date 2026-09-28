import { describe, expect, it } from 'vitest';
import { avvisoOrologio } from './orologio';

const ADESSO = Date.parse('2026-09-28T06:30:00Z');
const spostato = (minuti: number) => new Date(ADESSO + minuti * 60_000).toISOString();

describe("l'ora del server confrontata con quella del browser", () => {
  it('pochi secondi o un minuto non sono un problema', () => {
    expect(avvisoOrologio(spostato(0), ADESSO)).toBeNull();
    expect(avvisoOrologio(spostato(1), ADESSO)).toBeNull();
  });

  it('due ore avanti, come in produzione il 26 e il 28 settembre', () => {
    expect(avvisoOrologio(spostato(120), ADESSO)?.titolo).toBe("L'ora del server è avanti di 2 ore rispetto a questo computer");
  });

  it('qualche minuto indietro', () => {
    expect(avvisoOrologio(spostato(-5), ADESSO)?.titolo).toBe("L'ora del server è indietro di 5 minuti rispetto a questo computer");
  });

  it("un'ora illeggibile non produce un avviso sbagliato", () => {
    expect(avvisoOrologio('non è una data', ADESSO)).toBeNull();
  });
});
