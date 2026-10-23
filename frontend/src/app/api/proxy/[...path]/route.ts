import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const ACCESS_COOKIE = 'dp_access';
const REFRESH_COOKIE = 'dp_refresh';
const ADMIN_COOKIE = 'dp_admin';
const MERCHANT_LOGIN_PATHS = new Set([
  'auth/login',
  'auth/reactivate',
  'auth/google/exchange',
  'auth/google/complete',
]);
const FORWARDED_REQUEST_HEADERS = [
  'accept',
  'content-type',
  'idempotency-key',
  'last-event-id',
  'x-request-id',
] as const;
const FORWARDED_RESPONSE_HEADERS = [
  'cache-control',
  'content-type',
  'retry-after',
  'x-request-id',
] as const;

type Context = { params: { path: string[] } };
type TokenResponse = {
  data?: {
    access_token?: unknown;
    refresh_token?: unknown;
    expires_in?: unknown;
    token_type?: unknown;
  };
};

function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax' as const,
    path: '/api/proxy',
    maxAge,
  };
}

function setSessionCookies(
  response: NextResponse,
  accessToken: string,
  refreshToken: string | undefined,
  expiresIn: number,
) {
  const refreshDays = Number(process.env.REFRESH_TOKEN_EXPIRE_TIME ?? '30');
  response.cookies.set(ACCESS_COOKIE, accessToken, cookieOptions(expiresIn));
  if (refreshToken) {
    response.cookies.set(REFRESH_COOKIE, refreshToken, cookieOptions(refreshDays * 86400));
  }
  response.cookies.set('dp_session', '1', {
    httpOnly: false,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    path: '/',
    maxAge: refreshDays * 86400,
  });
}

function clearCookies(response: NextResponse, admin = false) {
  const options = { path: '/api/proxy', maxAge: 0 };
  if (admin) {
    response.cookies.set(ADMIN_COOKIE, '', options);
    response.cookies.set('dp_admin', '', { path: '/', maxAge: 0 });
  } else {
    response.cookies.set(ACCESS_COOKIE, '', options);
    response.cookies.set(REFRESH_COOKIE, '', options);
    response.cookies.set('dp_session', '', { path: '/', maxAge: 0 });
  }
}

async function proxy(request: NextRequest, context: Context) {
  const backend = process.env.BACKEND_INTERNAL_URL;
  if (!backend) {
    return NextResponse.json({ error: { code: 'SERVICE_UNAVAILABLE' } }, { status: 503 });
  }

  const path = context.params.path.map((part) => encodeURIComponent(part)).join('/');
  const isAdmin = path.startsWith('admin/');
  const isRefresh = path === 'auth/refresh' && request.method === 'POST';
  const isMerchantLogin = request.method === 'POST' && MERCHANT_LOGIN_PATHS.has(path);
  const isAdminLogin = request.method === 'POST' && path === 'admin/auth/login';
  const isMerchantLogout =
    request.method === 'POST' &&
    (path === 'auth/logout' || path === 'auth/me/deactivate');
  const isAdminLogout = request.method === 'POST' && path === 'admin/auth/logout';
  const isGoogleStart = request.method === 'GET' && path === 'auth/google';
  const isGoogleCallback = request.method === 'GET' && path === 'auth/google/callback';
  const isGoogleRedirect = isGoogleStart || isGoogleCallback;

  if (
    ['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method) &&
    request.headers.get('origin') !== request.nextUrl.origin
  ) {
    return NextResponse.json({ error: { code: 'CSRF_REJECTED' } }, { status: 403 });
  }

  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (isGoogleCallback) {
    const session = request.cookies.get('session')?.value;
    if (session) headers.set('cookie', `session=${session}`);
  }

  if (isRefresh) {
    const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
    if (!refreshToken) {
      const response = NextResponse.json({ error: { code: 'UNAUTHENTICATED' } }, { status: 401 });
      clearCookies(response);
      return response;
    }
    headers.set('content-type', 'application/json');
  } else {
    const token = isAdmin
      ? request.cookies.get(ADMIN_COOKIE)?.value
      : request.cookies.get(ACCESS_COOKIE)?.value;
    const explicitAuthorization = request.headers.get('authorization');
    if (token) headers.set('authorization', `Bearer ${token}`);
    else if (explicitAuthorization) headers.set('authorization', explicitAuthorization);
  }

  let body: BodyInit | null | undefined;
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    if (isRefresh) {
      body = JSON.stringify({ refresh_token: request.cookies.get(REFRESH_COOKIE)?.value });
    } else {
      body = request.body as BodyInit | null;
    }
  }

  const target = new URL(`/api/v1/${path}`, backend);
  target.search = request.nextUrl.search;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: 'no-store',
      redirect: isGoogleRedirect ? 'manual' : 'follow',
      ...(body ? { duplex: 'half' } : {}),
    } as RequestInit);
  } catch {
    return NextResponse.json({ error: { code: 'UPSTREAM_UNAVAILABLE' } }, { status: 502 });
  }

  if (isGoogleRedirect && upstream.status >= 300 && upstream.status < 400) {
    const location = upstream.headers.get('location');
    if (location) {
      const destination = new URL(location);
      const frontend = process.env.FRONTEND_URL;
      const allowedDestination = isGoogleStart
        ? destination.protocol === 'https:' && destination.hostname === 'accounts.google.com'
        : Boolean(
            frontend &&
              destination.origin === new URL(frontend).origin &&
              destination.pathname === '/auth/google',
          );
      if (!allowedDestination) {
        return NextResponse.json({ error: { code: 'INVALID_OAUTH_REDIRECT' } }, { status: 502 });
      }

      const response = NextResponse.redirect(destination, upstream.status);
      if (isGoogleStart) {
        const rawCookie = upstream.headers.get('set-cookie');
        const pair = rawCookie?.split(';', 1)[0];
        const separator = pair?.indexOf('=') ?? -1;
        if (pair && separator > 0 && pair.slice(0, separator) === 'session') {
          response.cookies.set('session', pair.slice(separator + 1), {
            httpOnly: true,
            secure: process.env.NODE_ENV === 'production',
            sameSite: 'lax',
            path: '/',
            maxAge: 600,
          });
        }
      } else {
        response.cookies.set('session', '', { path: '/', maxAge: 0 });
      }
      return response;
    }
  }

  const responseHeaders = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }

  if (isMerchantLogin || isRefresh || isAdminLogin) {
    const payload = (await upstream.json().catch(() => null)) as TokenResponse | null;
    const data = payload?.data;
    const accessToken = data?.access_token;
    const refreshToken = data?.refresh_token;
    const expiresIn = Number(data?.expires_in);

    if (
      upstream.ok &&
      typeof accessToken === 'string' &&
      Number.isFinite(expiresIn) &&
      expiresIn > 0
    ) {
      const safePayload = {
        ...payload,
        data: {
          token_type: typeof data?.token_type === 'string' ? data.token_type : 'bearer',
          expires_in: expiresIn,
        },
      };
      const response = NextResponse.json(safePayload, {
        status: upstream.status,
        headers: responseHeaders,
      });
      if (isAdminLogin) {
        response.cookies.set(ADMIN_COOKIE, accessToken, cookieOptions(expiresIn));
        response.cookies.set('dp_admin', '1', {
          httpOnly: false,
          secure: process.env.NODE_ENV === 'production',
          sameSite: 'lax',
          path: '/',
          maxAge: expiresIn,
        });
      } else {
        setSessionCookies(
          response,
          accessToken,
          typeof refreshToken === 'string' ? refreshToken : undefined,
          expiresIn,
        );
      }
      return response;
    }

    const response = NextResponse.json(payload ?? {}, {
      status: upstream.status,
      headers: responseHeaders,
    });
    if ((isRefresh && !upstream.ok) || (isAdmin && upstream.status === 401)) {
      clearCookies(response, isAdmin);
    }
    return response;
  }

  if (upstream.status === 204 || request.method === 'HEAD') {
    const response = new NextResponse(null, { status: upstream.status, headers: responseHeaders });
    if (isMerchantLogout) clearCookies(response);
    if (isAdminLogout) clearCookies(response, true);
    return response;
  }

  const response = new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
  if (isMerchantLogout) clearCookies(response);
  if (isAdminLogout) clearCookies(response, true);
  if (isAdmin && upstream.status === 401) clearCookies(response, true);
  return response;
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
