'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useMutation } from '@tanstack/react-query';
import { ArrowRight, Eye, EyeOff, Loader2, Lock, ShieldCheck } from 'lucide-react';
import { apiRequest, errorMessage } from '@/lib/api';
import type { AdminToken } from '@/lib/types';
import { useAdminAuthStore } from '@/stores/admin-auth';
import { Brand } from '@/components/brand';
import { Input } from '@/components/ui/input';
import { Alert } from '@/components/ui/alert';

export default function AdminLoginPage() {
  const router = useRouter();
  const token = useAdminAuthStore((state) => state.token);
  const setToken = useAdminAuthStore((state) => state.setToken);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (token) router.replace('/admin');
  }, [router, token]);

  const login = useMutation({
    mutationFn: () =>
      apiRequest<AdminToken>('/admin/auth/login', {
        method: 'POST',
        body: { email: email.trim(), password },
        admin: true,
        noRefresh: true,
        noRedirect: true,
      }),
    onSuccess: (data) => {
      setToken(data.access_token);
      router.replace('/admin');
    },
    onError: (mutationError) => setError(errorMessage(mutationError)),
  });

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-ink-950 px-4 py-10">
      <div className="absolute -left-32 top-10 h-96 w-96 rounded-full bg-brand-500/10 blur-3xl" />
      <div className="absolute -right-24 bottom-0 h-80 w-80 rounded-full bg-amber-300/10 blur-3xl" />
      <div
        className="absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage:
            'linear-gradient(#ffffff 1px, transparent 1px), linear-gradient(90deg, #ffffff 1px, transparent 1px)',
          backgroundSize: '56px 56px',
        }}
      />

      <div className="relative w-full max-w-md">
        <div className="mb-6 flex items-center justify-between">
          <Brand light />
          <span className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-300">
            <ShieldCheck className="h-3 w-3 text-brand-300" /> Operator access
          </span>
        </div>

        <div className="rounded-3xl border border-white/10 bg-white p-6 shadow-float sm:p-8">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-ink-950 text-white">
            <Lock className="h-5 w-5" />
          </div>
          <h1 className="mt-5 text-2xl font-semibold tracking-[-0.03em] text-ink-950">
            Admin console
          </h1>
          <p className="mt-1.5 text-[12px] leading-6 text-ink-500">
            Read-only installation visibility. Operator accounts are provisioned separately.
          </p>

          <form
            className="mt-6 space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              setError(null);
              login.mutate();
            }}
          >
            <div>
              <label
                htmlFor="admin-email"
                className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500"
              >
                Operator email
              </label>
              <Input
                id="admin-email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="ops@disputepilot.app"
                required
              />
            </div>
            <div>
              <label
                htmlFor="admin-password"
                className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500"
              >
                Password
              </label>
              <div className="relative">
                <Input
                  id="admin-password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="••••••••••••"
                  required
                  className="pr-11"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((value) => !value)}
                  className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-ink-400 hover:bg-ink-50 hover:text-ink-700"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {error ? <Alert tone="danger">{error}</Alert> : null}

            <button
              type="submit"
              disabled={login.isPending}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-ink-950 px-4 py-3 text-[13px] font-semibold text-white transition hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {login.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              Sign in to admin
              {!login.isPending ? <ArrowRight className="h-4 w-4" /> : null}
            </button>
          </form>

          <div className="mt-5 rounded-xl bg-ink-50 px-3.5 py-3 text-[10px] leading-5 text-ink-500">
            This console is read-only. It never exposes Paystack keys, password hashes or webhook
            secrets.
          </div>
        </div>

        <p className="mt-5 text-center text-[10px] text-ink-500">
          Merchant?{' '}
          <a href="/login" className="font-semibold text-ink-300 hover:text-white">
            Sign in to your workspace
          </a>
        </p>
      </div>
    </div>
  );
}
