import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'; import { formatDate, formatQuantity, formatRelativeTime } from './format'; describe('Italian formatting', () => { it('formats dates in Europe/Rome', () => expect(formatDate('2026-03-12T23:30:00Z')).toContain('13 mar 2026')); it('formats decimal quantities', () => expect(formatQuantity(1234.5, 'PZ')).toBe('1234,5 PZ')); it('formats missing values', () => expect(formatQuantity(null)).toBe('—')); });

describe('formatRelativeTime', () => {
  const adesso = new Date('2026-09-03T12:00:00Z');
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(adesso); });
  afterEach(() => { vi.useRealTimers(); });

  it('dice quanto tempo è passato, non l\'orario', () => {
    expect(formatRelativeTime('2026-09-03T09:00:00Z')).toBe('3 ore fa');
    expect(formatRelativeTime('2026-09-02T12:00:00Z')).toBe('ieri');
  });

  it('guarda anche avanti: una garanzia scade nel futuro', () => {
    expect(formatRelativeTime('2026-09-13T12:00:00Z')).toBe('tra 10 giorni');
  });

  it('sotto il minuto non conta i secondi', () => {
    expect(formatRelativeTime('2026-09-03T11:59:30Z')).toBe('adesso');
  });

  it('senza data non inventa niente', () => {
    expect(formatRelativeTime(null)).toBe('—');
  });
});
