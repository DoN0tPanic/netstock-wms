const dateFormatter = new Intl.DateTimeFormat('it-IT', { timeZone: 'Europe/Rome', dateStyle: 'medium' });
const dateTimeFormatter = new Intl.DateTimeFormat('it-IT', { timeZone: 'Europe/Rome', dateStyle: 'short', timeStyle: 'short' });
const quantityFormatter = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 2 });
export const formatDate = (value: string | Date | null | undefined): string => value ? dateFormatter.format(new Date(value)) : '—';
export const formatDateTime = (value: string | Date | null | undefined): string => value ? dateTimeFormatter.format(new Date(value)) : '—';
export const formatQuantity = (value: number | null | undefined, uom?: string): string => value === null || value === undefined ? '—' : `${quantityFormatter.format(value)}${uom ? ` ${uom}` : ''}`;
