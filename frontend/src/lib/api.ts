import {
  clearAdminToken,
  clearSession,
  getAdminToken,
  getSession,
  setSession,
} from './auth-storage';
import type { ApiErrorPayload, FileRef, PageMeta, Token } from './types';

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  headers?: Record<string, string>;
  admin?: boolean;
  noRefresh?: boolean;
  noRedirect?: boolean;
  signal?: AbortSignal;
};

type Envelope<T> = { data: T };
type ListEnvelope<T> = { data: T[]; meta: PageMeta };

export class ApiError extends Error {
  status: number;
  code: string;
  requestId: string | null;
  details: Record<string, string> | null;

  constructor(
    message: string,
    options: {
      status: number;
      code?: string;
      requestId?: string | null;
      details?: Record<string, string> | null;
    },
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = options.status;
    this.code = options.code ?? 'REQUEST_FAILED';
    this.requestId = options.requestId ?? null;
    this.details = options.details ?? null;
  }
}

let merchantRefresh: Promise<Token | null> | null = null;

export async function refreshMerchantSession(): Promise<Token | null> {
  if (merchantRefresh) return merchantRefresh;
  const session = getSession();
  if (!session?.refresh_token) return null;

  merchantRefresh = (async () => {
    try {
      const response = await fetch('/api/proxy/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: session.refresh_token }),
      });
      if (!response.ok) return null;
      const payload = (await response.json()) as Envelope<Token>;
      setSession(payload.data);
      return payload.data;
    } catch {
      return null;
    } finally {
      merchantRefresh = null;
    }
  })();

  return merchantRefresh;
}

function redirect(path: string) {
  if (typeof window === 'undefined') return;
  if (window.location.pathname === path) return;
  window.location.assign(path);
}

async function parseError(response: Response): Promise<ApiError> {
  let message = response.statusText || 'Something went wrong';
  let code = 'REQUEST_FAILED';
  let requestId: string | null = null;
  let details: Record<string, string> | null = null;

  try {
    const payload = (await response.json()) as ApiErrorPayload;
    if (payload.error) {
      message = payload.error.message;
      code = payload.error.code;
      requestId = payload.error.request_id;
      details = payload.error.details ?? null;
    } else if ('detail' in payload) {
      const detail = (payload as { detail?: unknown }).detail;
      message = typeof detail === 'string' ? detail : JSON.stringify(detail);
    }
  } catch {
    const text = await response.text().catch(() => '');
    if (text) message = text;
  }

  return new ApiError(message, { status: response.status, code, requestId, details });
}

async function perform<T>(
  path: string,
  options: RequestOptions,
  token: string | null,
  retry = true,
): Promise<T> {
  const headers: Record<string, string> = { ...options.headers };
  const isForm = options.body instanceof FormData;

  if (options.body !== undefined && !isForm) {
    headers['Content-Type'] = 'application/json';
  }
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`/api/proxy${path}`, {
    method: options.method ?? 'GET',
    headers,
    body:
      options.body === undefined
        ? undefined
        : isForm
          ? (options.body as FormData)
          : JSON.stringify(options.body),
    signal: options.signal,
  });

  if (response.status === 401 && retry && !options.noRefresh) {
    if (options.admin) {
      clearAdminToken();
      if (!options.noRedirect) redirect('/admin/login');
    } else {
      const refreshed = await refreshMerchantSession();
      if (refreshed) return perform<T>(path, options, refreshed.access_token, false);
      clearSession();
      if (!options.noRedirect) redirect('/login');
    }
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = options.admin ? getAdminToken() : (getSession()?.access_token ?? null);
  const payload = await perform<Envelope<T>>(path, options, token);
  return payload.data;
}

export async function apiList<T>(
  path: string,
  options: RequestOptions = {},
): Promise<ListEnvelope<T>> {
  const token = options.admin ? getAdminToken() : (getSession()?.access_token ?? null);
  return perform<ListEnvelope<T>>(path, options, token);
}

export async function apiBlob(path: string, options: RequestOptions = {}): Promise<Blob> {
  const token = options.admin ? getAdminToken() : (getSession()?.access_token ?? null);
  const headers: Record<string, string> = { ...options.headers };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`/api/proxy${path}`, {
    method: options.method ?? 'GET',
    headers,
    signal: options.signal,
  });
  if (!response.ok) throw await parseError(response);
  return response.blob();
}

export async function uploadFiles(files: File[]): Promise<FileRef[]> {
  const form = new FormData();
  files.forEach((file) => form.append('files', file));
  const result = await apiRequest<{ files: FileRef[] }>('/uploads', {
    method: 'POST',
    body: form,
  });
  return result.files;
}

export function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Something went wrong. Please try again.';
}

export function logIn(token: Token) {
  setSession(token);
}

export function logOutMerchant() {
  clearSession();
}

export function logOutAdmin() {
  clearAdminToken();
}
