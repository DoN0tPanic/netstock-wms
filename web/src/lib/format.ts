const dateFormatter = new Intl.DateTimeFormat('it-IT', { timeZone: 'Europe/Rome', dateStyle: 'medium' });
const dateTimeFormatter = new Intl.DateTimeFormat('it-IT', { timeZone: 'Europe/Rome', dateStyle: 'short', timeStyle: 'short' });
const quantityFormatter = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 2 });
export const formatDate = (value: string | Date | null | undefined): string => value ? dateFormatter.format(new Date(value)) : '—';
export const formatDateTime = (value: string | Date | null | undefined): string => value ? dateTimeFormatter.format(new Date(value)) : '—';
export const formatQuantity = (value: number | null | undefined, uom?: string): string => value === null || value === undefined ? '—' : `${quantityFormatter.format(value)}${uom ? ` ${uom}` : ''}`;

const relativeFormatter = new Intl.RelativeTimeFormat('it', { numeric: 'auto' });
const SCAGLIONI: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ['year', 31_536_000_000], ['month', 2_592_000_000], ['day', 86_400_000],
  ['hour', 3_600_000], ['minute', 60_000],
];

/** «2 ore fa», «ieri», «fra 3 giorni».
 *
 * Su una pagina che si guarda di sfuggita conta quanto tempo è passato, non
 * l'orario esatto: «3 minuti fa» si capisce senza sottrarre niente. L'orario
 * preciso resta comunque, nel `title` di chi lo mostra.
 */
export const formatRelativeTime = (value: string | Date | null | undefined): string => {
  if (!value) return '—';
  const scarto = new Date(value).getTime() - Date.now();
  for (const [unita, millisecondi] of SCAGLIONI) {
    if (Math.abs(scarto) >= millisecondi) {
      return relativeFormatter.format(Math.round(scarto / millisecondi), unita);
    }
  }
  return 'adesso';
};
