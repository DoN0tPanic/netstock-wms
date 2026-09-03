import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { GlobalSearch } from './GlobalSearch';

function Location() { return <span data-testid="location">{useLocation().pathname}</span>; }
describe('GlobalSearch', () => {
  afterEach(() => { vi.restoreAllMocks(); });
  it('attende il debounce, raggruppa i risultati e naviga usando path', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ results: [{ type: 'unit', id: 'u1', label: 'SER-001', sublabel: 'Switch', path: '/units/u1' }] }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/']}><GlobalSearch/><Routes><Route path="*" element={<Location/>}/></Routes></MemoryRouter></QueryClientProvider>);
    fireEvent.change(screen.getByLabelText('Ricerca globale'), { target: { value: 'SE' } });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(await screen.findByText('Unità')).toBeInTheDocument();
    fireEvent.click(screen.getByText('SER-001'));
    expect(screen.getByTestId('location')).toHaveTextContent('/units/u1');
  });
});
