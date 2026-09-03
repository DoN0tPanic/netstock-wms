import type { ApiErrorBody } from '../types/api';

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string, public readonly details: Record<string, unknown>) { super(message); this.name = 'ApiError'; }
}
type QueryValue = string | number | boolean | null | undefined;
export interface RequestOptions extends Omit<RequestInit, 'body'> { body?: unknown; query?: Record<string, QueryValue>; idempotencyKey?: string }

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = new URL(`/api/v1${path}`, window.location.origin);
  Object.entries(options.query ?? {}).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value)); });
  const headers = new Headers(options.headers);
  headers.set('Accept', 'application/json');
  headers.set('X-Requested-With', 'XMLHttpRequest');
  if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey);
  const isForm = options.body instanceof FormData;
  if (options.body !== undefined && !isForm) headers.set('Content-Type', 'application/json');
  const requestBody: BodyInit | undefined = options.body === undefined ? undefined : isForm ? options.body as FormData : JSON.stringify(options.body);
  const response = await fetch(url, { ...options, headers, credentials: 'include', body: requestBody });
  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try { body = await response.json() as ApiErrorBody; } catch { body = undefined; }
    throw new ApiError(response.status, body?.error.code ?? 'HTTP_ERROR', body?.error.message ?? 'Si è verificato un errore di comunicazione.', body?.error.details ?? {});
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function apiDownload(path: string, query: Record<string, QueryValue>): Promise<Blob> {
  const url = new URL(`/api/v1${path}`, window.location.origin);
  // Stessa regola di `apiRequest`, e non è pignoleria: qui mancava, e un
  // filtro lasciato vuoto partiva come `location=`. Gli endpoint di
  // esportazione dichiarano quei parametri come UUID, quindi rispondevano
  // 422 — cioè «Esporta CSV» falliva sempre, perché i filtri vuoti sono la
  // condizione normale della pagina.
  Object.entries(query).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value)); });
  const response = await fetch(url, { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
  if (!response.ok) throw new ApiError(response.status, 'EXPORT_ERROR', 'Impossibile generare l’esportazione.', {});
  return response.blob();
}
