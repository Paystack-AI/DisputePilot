import { format, formatDistanceToNowStrict, parseISO } from 'date-fns';
import type { Currency } from './types';

export function formatMoney(amountMinor: number | null | undefined, currency: Currency = 'NGN') {
  if (amountMinor === null || amountMinor === undefined) return '—';
  const amount = amountMinor / 100;
  return new Intl.NumberFormat('en-NG', {
    style: 'currency',
    currency,
    maximumFractionDigits: amount % 1 === 0 ? 0 : 2,
  }).format(amount);
}

export function compactMoney(amountMinor: number | null | undefined, currency: Currency = 'NGN') {
  if (amountMinor === null || amountMinor === undefined) return '—';
  const amount = amountMinor / 100;
  return new Intl.NumberFormat('en-NG', {
    style: 'currency',
    currency,
    notation: amount >= 1_000_000 ? 'compact' : 'standard',
    maximumFractionDigits: 0,
  }).format(amount);
}

export function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat('en-NG').format(value);
}

export function formatDate(value: string | null | undefined) {
  if (!value) return '—';
  return format(parseISO(value), 'd MMM yyyy');
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return '—';
  return format(parseISO(value), 'd MMM yyyy, h:mm a');
}

export function formatTime(value: string | null | undefined) {
  if (!value) return '—';
  return format(parseISO(value), 'h:mm a');
}

export function timeAgo(value: string | null | undefined) {
  if (!value) return '—';
  return `${formatDistanceToNowStrict(parseISO(value))} ago`;
}

export function percent(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined) return '—';
  return `${value.toFixed(digits)}%`;
}

export function initials(name: string | null | undefined) {
  if (!name) return 'DP';
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('');
}

export function titleCase(value: string | null | undefined) {
  if (!value) return '—';
  return value.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function queryString(params: Record<string, string | number | boolean | undefined | null>) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return query ? `?${query}` : '';
}

export function hoursUntil(value: string, serverTime?: string) {
  const now = serverTime ? parseISO(serverTime).getTime() : Date.now();
  return (parseISO(value).getTime() - now) / 3_600_000;
}

export function deadlineLabel(value: string, serverTime?: string) {
  const hours = hoursUntil(value, serverTime);
  const absolute = Math.abs(hours);
  const days = Math.floor(absolute / 24);
  const remainingHours = Math.floor(absolute % 24);
  const minutes = Math.floor((absolute % 1) * 60);
  if (days > 0) return `${days}d ${remainingHours}h`;
  if (remainingHours > 0) return `${remainingHours}h ${minutes}m`;
  return `${minutes}m`;
}

/** A datetime-local input's value (local time, to the minute) for an ISO time or now */
export function toLocalInput(value?: string | Date) {
  const date = value ? new Date(value) : new Date();
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

const CHANNELS: Record<string, string> = {
  card: 'Card',
  bank: 'Bank',
  bank_transfer: 'Transfer',
  mobile_money: 'Mobile money',
  ussd: 'USSD',
  qr: 'QR',
  eft: 'EFT',
  apple_pay: 'Apple Pay',
  other: 'Other',
};

/** How a payment channel reads in a table: USSD, not Ussd */
export function channelLabel(channel: string | null | undefined) {
  if (!channel) return '—';
  return CHANNELS[channel] ?? titleCase(channel);
}
