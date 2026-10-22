'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeftRight,
  CircleCheck,
  LayoutGrid,
  LifeBuoy,
  Settings2,
  ShieldCheck,
  ShieldAlert,
  ShoppingBag,
  Truck,
  Users,
  X,
} from 'lucide-react';
import { apiRequest } from '@/lib/api';
import { cn } from '@/lib/cn';
import type { DisputeStats, Merchant, ReconciliationSummary } from '@/lib/types';
import { Brand } from '@/components/brand';

const navigation = [
  { href: '/', label: 'Dashboard', icon: LayoutGrid },
  { href: '/transactions', label: 'Transactions', icon: ArrowLeftRight },
  { href: '/disputes', label: 'Disputes', icon: ShieldAlert, badge: 'disputes' },
  { href: '/orders', label: 'Orders', icon: ShoppingBag },
  { href: '/fulfillments', label: 'Fulfillments', icon: Truck },
  { href: '/customers', label: 'Customers', icon: Users },
  { href: '/reconciliation', label: 'Reconciliation', icon: CircleCheck, badge: 'review' },
  { href: '/trust', label: 'TrustLayer', icon: ShieldCheck },
] as const;

export function Sidebar({ mobileOpen, onClose }: { mobileOpen?: boolean; onClose?: () => void }) {
  const pathname = usePathname();
  const { data: merchant } = useQuery({
    queryKey: ['merchant', 'me'],
    queryFn: () => apiRequest<Merchant>('/auth/me'),
    staleTime: 5 * 60_000,
  });
  const { data: summary } = useQuery({
    queryKey: ['reconciliation', 'summary'],
    queryFn: () => apiRequest<ReconciliationSummary>('/reconciliation/summary'),
    staleTime: 60_000,
    retry: false,
  });
  const { data: disputeStats } = useQuery({
    queryKey: ['disputes', 'stats'],
    queryFn: () => apiRequest<DisputeStats>('/disputes/stats'),
    staleTime: 60_000,
    retry: false,
  });

  const isActive = (href: string) => (href === '/' ? pathname === '/' : pathname.startsWith(href));
  const mode = merchant?.paystack.mode;

  const content = (
    <div className="flex h-full flex-col bg-navy text-white">
      <div className="flex h-16 items-center justify-between px-5">
        <Link href="/" onClick={onClose}>
          <Brand light />
        </Link>
        <button
          type="button"
          className="rounded-md p-1.5 text-white/60 hover:bg-white/10 hover:text-white lg:hidden"
          onClick={onClose}
          aria-label="Close menu"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <Link
        href="/settings/account"
        onClick={onClose}
        className="mx-3 rounded-lg border border-white/10 px-3 py-2.5 transition hover:bg-white/[0.04]"
      >
        <p className="truncate text-[13px] font-medium text-white">
          {merchant?.business_name ?? 'Your business'}
        </p>
        <span
          className={cn(
            'mt-1 inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2 py-px text-[10px] font-medium',
            mode ? 'text-white' : 'text-white/60',
          )}
        >
          <span
            className={cn(
              'h-1.5 w-1.5 rounded-full',
              mode === 'live' ? 'bg-emerald-500' : mode === 'test' ? 'bg-amber-500' : 'bg-white/40',
            )}
          />
          {mode === 'live' ? 'Live' : mode === 'test' ? 'Test mode' : 'Not connected'}
        </span>
      </Link>

      <nav className="mt-4 flex-1 space-y-0.5 overflow-y-auto px-3 scrollbar-thin">
        {navigation.map((item) => {
          const Icon = item.icon;
          const badge = 'badge' in item ? item.badge : undefined;
          const count =
            badge === 'review'
              ? summary?.needs_review
              : badge === 'disputes'
                ? disputeStats?.open
                : undefined;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onClose}
              className={cn('sidebar-link', isActive(item.href) && 'sidebar-link-active')}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="flex-1">{item.label}</span>
              {count ? (
                <span
                  className={cn(
                    'min-w-[18px] rounded-full px-1.5 text-center text-[10px] font-semibold leading-[18px] tabular-nums',
                    badge === 'disputes' ? 'bg-red-500 text-white' : 'bg-amber-500 text-navy',
                  )}
                >
                  {count}
                </span>
              ) : null}
            </Link>
          );
        })}
        <Link
          href="/settings"
          onClick={onClose}
          className={cn('sidebar-link', isActive('/settings') && 'sidebar-link-active')}
        >
          <Settings2 className="h-4 w-4 shrink-0" />
          <span className="flex-1">Settings</span>
        </Link>
      </nav>

      <div className="p-3">
        <a
          href="mailto:support@disputepilot.app"
          className="block rounded-lg bg-white/[0.05] px-3 py-3 transition hover:bg-white/[0.08]"
        >
          <p className="flex items-center gap-1.5 text-[12px] font-medium text-white">
            <LifeBuoy className="h-3.5 w-3.5" /> Need help?
          </p>
          <p className="mt-0.5 text-[11px] leading-4 text-white/55">
            Our support team is here for you.
          </p>
        </a>
      </div>
    </div>
  );

  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[var(--sidebar-width)] lg:block">
        {content}
      </aside>
      {mobileOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/50"
            onClick={onClose}
            aria-label="Close menu"
          />
          <aside className="relative h-full w-[272px] shadow-float">{content}</aside>
        </div>
      ) : null}
    </>
  );
}
