'use client';

/**
 * Starts Google sign in. A full navigation, not a fetch: the api redirects to Google, and
 * Google redirects back to /auth/google with a one-time code.
 */
export function GoogleButton({
  intent = 'sign_in',
  label = 'Continue with Google',
}: {
  intent?: 'sign_in' | 'reactivate';
  label?: string;
}) {
  return (
    <>
      <div className="mb-4 flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-400">
        <span className="h-px flex-1 bg-line" />
        or
        <span className="h-px flex-1 bg-line" />
      </div>
      <a
        href={`/api/proxy/auth/google?intent=${intent}`}
        className="flex h-12 w-full items-center justify-center gap-2.5 rounded-xl bg-surface text-[14px] font-semibold text-ink-800 ring-1 ring-inset ring-line transition hover:bg-ink-50"
      >
        <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" aria-hidden>
          <path
            fill="#4285F4"
            d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z"
          />
          <path
            fill="#34A853"
            d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z"
          />
          <path
            fill="#FBBC05"
            d="M5.84 14.1A6.6 6.6 0 0 1 5.5 12c0-.73.13-1.44.34-2.1V7.06H2.18A11 11 0 0 0 1 12c0 1.78.43 3.45 1.18 4.94l3.66-2.84z"
          />
          <path
            fill="#EA4335"
            d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15A10.96 10.96 0 0 0 12 1 11 11 0 0 0 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
          />
        </svg>
        {label}
      </a>
    </>
  );
}
