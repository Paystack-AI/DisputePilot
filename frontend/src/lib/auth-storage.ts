const MERCHANT_MARKER = 'dp_session';
const ADMIN_MARKER = 'dp_admin';

function hasCookie(name: string): boolean {
  if (typeof document === 'undefined') return false;
  return document.cookie.split('; ').some((cookie) => cookie.startsWith(`${name}=1`));
}

function writeMarker(name: string, present: boolean, maxAge = 60 * 60 * 24 * 30) {
  if (typeof document === 'undefined') return;
  const secure = window.location.protocol === 'https:' ? '; Secure' : '';
  document.cookie = `${name}=${present ? '1' : ''}; Path=/; Max-Age=${present ? maxAge : 0}; SameSite=Lax${secure}`;
}

export function getSession(): boolean {
  return hasCookie(MERCHANT_MARKER);
}

export function setSession() {
  writeMarker(MERCHANT_MARKER, true);
}

export function clearSession() {
  writeMarker(MERCHANT_MARKER, false);
}

export function getAdminToken(): boolean {
  return hasCookie(ADMIN_MARKER);
}

export function setAdminToken() {
  writeMarker(ADMIN_MARKER, true, 60 * 60);
}

export function clearAdminToken() {
  writeMarker(ADMIN_MARKER, false);
}
