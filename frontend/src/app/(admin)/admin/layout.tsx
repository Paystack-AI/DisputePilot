'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowUpRight,
  Building2,
  LayoutDashboard,
  Loader2,
  LogOut,
  ShieldCheck,
  Store,
} from 'lucide-react';
import { apiRequest } from '@/lib/api';
import { cn } from '@/lib/cn';
import type { AdminProfile } from '@/lib/types';
import { useAdminAuthStore } from '@/stores/admin-auth';
import { Brand } from '@/components/brand';

const NAV = [
  { href: '/admin', label: 'Overview', icon: LayoutDashboard, exact: true },
  { href: '/admin/merchants', label: 'Merchants', icon: Store, exact: false },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const token = useAdminAuthStore((state) => state.token);
  const clear = useAdminAuthStore((state) => state.clear);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!token) {
      router.replace('/admin/login');
      return;
    }
    setReady(true);
  }, [router, token]);

  const profileQuery = useQuery({
    queryKey: ['admin', 'me'],
    queryFn: () => apiRequest<AdminProfile>('/admin/auth/me', { admin: true, noRedirect: true }),
    enabled: Boolean(token),
    retry: false,
  });

  useEffect(() => {
    if (profileQuery.isError) {
      clear();
      router.replace('/admin/login');
    }
  }, [clear, profileQuery.isError, router]);

  const logout = useMutation({
    mutationFn: () =>
      apiRequest<void>('/admin/auth/logout', { method: 'POST', admin: true, noRedirect: true }),
    onSettled: () => {
      queryClient.clear();
      clear();
      router.replace('/admin/login');
    },
  });

  if (!ready || !token) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-5 bg-canvas">
        <Brand />
        <div className="flex items-center gap-2 text-sm text-ink-500">
          <Loader2 className="h-4 w-4 animate-spin text-brand-600" /> Opening admin console
        </div>
      </div>
    );
  }

  const profile = profileQuery.data;
  const isActive = (href: string, exact: boolean) =>
    exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <div className="min-h-screen bg-canvas">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col bg-ink-950 px-4 py-5 lg:flex">
        <div className="px-2">
          <Brand light />
        </div>
        <div className="mt-5 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2.5">
          <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-brand-300">
            <ShieldCheck className="h-3 w-3" /> Operator console
          </p>
          <p className="mt-1 text-[10px] leading-4 text-ink-400">
            Read-only installation visibility
          </p>
        </div>
        <nav className="mt-6 space-y-1">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                'flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-[12px] font-medium transition',
                isActive(item.href, item.exact)
                  ? 'bg-white/10 text-white'
                  : 'text-ink-300 hover:bg-white/5 hover:text-white',
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="mt-auto space-y-3">
          <Link
            href="/"
            className="flex items-center justify-between gap-2 rounded-xl border border-white/10 px-3 py-2.5 text-[11px] font-medium text-ink-300 transition hover:border-white/20 hover:text-white"
          >
            Merchant app <ArrowUpRight className="h-3.5 w-3.5" />
          </Link>
          <div className="rounded-xl bg-white/[0.04] p-3">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500/20 text-[11px] font-bold text-brand-300">
                {(profile?.name ?? profile?.email ?? 'A').slice(0, 1).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[11px] font-semibold text-white">
                  {profile?.name ?? 'Operator'}
                </p>
                <p className="truncate text-[9px] text-ink-400">{profile?.email ?? '—'}</p>
              </div>
              <button
                type="button"
                onClick={() => logout.mutate()}
                className="flex h-7 w-7 items-center justify-center rounded-lg text-ink-400 transition hover:bg-white/10 hover:text-white"
                aria-label="Sign out"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>
      </aside>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 border-b border-line bg-warm-white/90 backdrop-blur">
          <div className="flex items-center justify-between gap-3 px-4 py-3 sm:px-6">
            <div className="flex items-center gap-3 lg:hidden">
              <Brand compact />
              <span className="text-[12px] font-semibold text-ink-900">Admin</span>
            </div>
            <div className="hidden items-center gap-2 text-[11px] text-ink-500 lg:flex">
              <Building2 className="h-3.5 w-3.5" />
              Installation overview
            </div>
            <div className="flex items-center gap-2">
              <span className="hidden rounded-full bg-brand-50 px-2.5 py-1 text-[9px] font-bold uppercase tracking-[0.1em] text-brand-700 sm:inline">
                Read only
              </span>
              <button
                type="button"
                onClick={() => logout.mutate()}
                className="flex items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-[11px] font-medium text-ink-600 transition hover:bg-white hover:text-ink-900"
              >
                <LogOut className="h-3.5 w-3.5" /> Sign out
              </button>
            </div>
          </div>
          <nav className="flex gap-1 overflow-x-auto border-t border-line px-3 py-2 lg:hidden">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-medium',
                  isActive(item.href, item.exact)
                    ? 'bg-ink-950 text-white'
                    : 'text-ink-500 hover:bg-white hover:text-ink-900',
                )}
              >
                <item.icon className="h-3.5 w-3.5" />
                {item.label}
              </Link>
            ))}
          </nav>
        </header>
        <main className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children}
        </main>
      </div>
    </div>
  );
}
