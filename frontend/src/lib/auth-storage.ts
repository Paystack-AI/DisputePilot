import type { Token } from './types';

const SESSION_KEY = 'disputepilot.session';
const ADMIN_KEY = 'disputepilot.admin';

function read<T>(key: string): T | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function write(key: string, value: unknown) {
  if (typeof window === 'undefined') return;
  window.localStorage.setItem(key, JSON.stringify(value));
}

function remove(key: string) {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(key);
}

export function getSession(): Token | null {
  return read<Token>(SESSION_KEY);
}

export function setSession(token: Token) {
  write(SESSION_KEY, token);
}

export function clearSession() {
  remove(SESSION_KEY);
}

export function getAdminToken(): string | null {
  return read<{ access_token: string }>(ADMIN_KEY)?.access_token ?? null;
}

export function setAdminToken(token: { access_token: string }) {
  write(ADMIN_KEY, token);
}

export function clearAdminToken() {
  remove(ADMIN_KEY);
}
