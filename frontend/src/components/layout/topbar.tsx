'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Bell,
  ChevronDown,
  Command,
  LogOut,
  Menu,
  Settings,
  ShieldCheck,
  UserRound,
} from 'lucide-react';
import { apiRequest, logOutMerchant } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDate } from '@/lib/format';
import type { Merchant, DisputeStats } from '@/lib/types';
import { useAuthStore } from '@/stores/auth';
import { Avatar } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

const pageNames: Record<string, string> = {
  '/': 'Dashboard',
  '/reconciliation': 'Reconciliation',
  '/disputes': 'Disputes',
  '/customers': 'Customers',
  '/orders': 'Orders',
  '/trust': 'TrustLayer',
  '/settings': 'Settings',
  '/fulfillments/new': 'Log fulfillment',
};

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const clearSession = useAuthStore((state) => state.clear);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const { data: merchant } = useQuery({
    queryKey: ['merchant', 'me'],
    queryFn: () => apiRequest<Merchant>('/auth/me'),
    staleTime: 5 * 60_000,
  });
  const { data: stats } = useQuery({
    queryKey: ['disputes', 'stats'],
    queryFn: () => apiRequest<DisputeStats>('/disputes/stats'),
    staleTime: 60_000,
  });

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const root = `/${pathname.split('/').filter(Boolean)[0] ?? ''}`;
  const pageName =
    pageNames[pathname] ??
    (pathname.startsWith('/disputes/')
      ? 'Dispute review'
      : pathname.startsWith('/customers/')
        ? 'Customer ledger'
        : pathname.startsWith('/orders/')
          ? 'Order'
          : pathname.startsWith('/reconciliation/session')
            ? 'Reconciliation session'
            : (pageNames[root] ?? 'Workspace'));

  const logout = async () => {
    try {
      await apiRequest('/auth/logout', { method: 'POST', noRedirect: true });
    } catch {
      // The local session is cleared regardless.
    }
    logOutMerchant();
    clearSession();
    queryClient.clear();
    router.replace('/login');
  };

  return (
    <header className="sticky top-0 z-20 flex h-[72px] items-center justify-between border-b border-line bg-canvas/85 px-4 backdrop-blur-xl sm:px-6 lg:px-8">
      <div className="flex min-w-0 items-center gap-3">
        <Button
          variant="outline"
          size="icon"
          className="lg:hidden"
          onClick={onMenu}
          aria-label="Open menu"
        >
          <Menu className="h-4 w-4" />
        </Button>
        <div className="hidden items-center gap-2 text-[13px] sm:flex">
          <span className="font-medium text-ink-400">Workspace</span>
          <span className="text-ink-300">/</span>
          <span className="font-semibold text-ink-800">{pageName}</span>
        </div>
        <div className="flex items-center gap-2 sm:hidden">
          <span className="truncate text-sm font-semibold text-ink-900">{pageName}</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <div className="mr-1 hidden items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 py-1.5 text-[11px] font-medium text-ink-400 xl:flex">
          <Command className="h-3 w-3" />
          <span>Quick nav</span>
          <kbd className="rounded border border-line bg-ink-50 px-1 text-[10px] text-ink-500">
            /
          </kbd>
        </div>

        <Link
          href="/disputes"
          className="relative flex h-10 w-10 items-center justify-center rounded-xl border border-line bg-white text-ink-500 transition hover:bg-ink-50 hover:text-ink-800"
          aria-label="Open disputes"
        >
          <Bell className="h-[18px] w-[18px]" />
          {stats?.open ? (
            <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-danger ring-2 ring-white" />
          ) : null}
        </Link>

        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            className="flex items-center gap-2 rounded-xl border border-line bg-white p-1.5 pr-2.5 transition hover:bg-ink-50"
          >
            <Avatar name={merchant?.business_name} size="sm" />
            <div className="hidden text-left sm:block">
              <p className="max-w-[140px] truncate text-[12px] font-semibold leading-4 text-ink-900">
                {merchant?.business_name ?? 'Your business'}
              </p>
              <p className="text-[10px] text-ink-400">{formatDate(new Date().toISOString())}</p>
            </div>
            <ChevronDown className="h-3.5 w-3.5 text-ink-400" />
          </button>

          {menuOpen ? (
            <div className="absolute right-0 top-12 w-60 overflow-hidden rounded-2xl border border-line bg-white shadow-float animate-fade-up">
              <div className="border-b border-line px-4 py-3">
                <p className="truncate text-[13px] font-semibold text-ink-900">
                  {merchant?.business_name}
                </p>
                <p className="mt-0.5 truncate text-[11px] text-ink-500">
                  {merchant?.email ?? merchant?.google_email ?? 'Merchant account'}
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <Badge tone={merchant?.paystack.connected ? 'success' : 'warning'} dot>
                    {merchant?.paystack.connected ? 'Paystack connected' : 'Paystack not connected'}
                  </Badge>
                </div>
              </div>
              <div className="p-1.5">
                <Link
                  href="/settings"
                  onClick={() => setMenuOpen(false)}
                  className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium text-ink-600 hover:bg-ink-50"
                >
                  <Settings className="h-4 w-4" /> Account settings
                </Link>
                <Link
                  href="/trust"
                  onClick={() => setMenuOpen(false)}
                  className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium text-ink-600 hover:bg-ink-50"
                >
                  <ShieldCheck className="h-4 w-4" /> Trust profile
                </Link>
                <Link
                  href="/settings#paystack"
                  onClick={() => setMenuOpen(false)}
                  className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium text-ink-600 hover:bg-ink-50"
                >
                  <UserRound className="h-4 w-4" /> Paystack connection
                </Link>
              </div>
              <div className="border-t border-line p-1.5">
                <button
                  type="button"
                  onClick={logout}
                  className={cn(
                    'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] font-medium text-danger hover:bg-red-50',
                  )}
                >
                  <LogOut className="h-4 w-4" /> Sign out
                </button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}
