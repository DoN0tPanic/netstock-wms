import { z } from 'zod';
export const normalizeSerial = (value: string): string => value.trim().toUpperCase().replace(/^(?:S\/N|SERIAL|SN)\s*:?\s*/i, '').replace(/\s+/g, '');
export const serialSchema = z.string().transform(normalizeSerial).pipe(z.string().min(3, 'Il seriale deve contenere almeno 3 caratteri.').max(64, 'Il seriale non può superare 64 caratteri.').regex(/^[A-Z0-9._-]+$/, 'Il seriale contiene caratteri non validi.'));
export const macAddressSchema = z.string().regex(/^([0-9A-Fa-f]{2}[:\-.]?){5}[0-9A-Fa-f]{2}$/, 'Indirizzo MAC non valido.');
export const validateSerialPattern = (serial: string, pattern?: string | null): boolean => !pattern || new RegExp(pattern).test(normalizeSerial(serial));
