'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowUpRight,
  Camera,
  CreditCard,
  CheckCircle2,
  LayoutDashboard,
  Settings,
  Shield,
  ShieldCheck,
  ShoppingBag,
  Truck,
  Users,
  X,
} from 'lucide-react';
import { apiRequest } from '@/lib/api';
import { cn } from '@/lib/cn';
import type { Dashboard, DisputeStats, ReconciliationSummary } from '@/lib/types';
import { Badge } from '@/components/ui/badge';
import { Brand } from '@/components/brand';
import { Button } from '@/components/ui/button';

const navigation = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/reconciliation', label: 'Reconciliation', icon: CheckCircle2, badge: 'review' },
  { href: '/disputes', label: 'Disputes', icon: Shield, badge: 'disputes' },
  { href: '/transactions', label: 'Transactions', icon: CreditCard },
  { href: '/orders', label: 'Orders', icon: ShoppingBag },
  { href: '/fulfillments', label: 'Fulfillments', icon: Truck },
  { href: '/customers', label: 'Customers', icon: Users },
  { href: '/trust', label: 'TrustLayer', icon: ShieldCheck },
];

export function Sidebar({
  businessName,
  mobileOpen,
  onClose,
}: {
  businessName?: string;
  mobileOpen?: boolean;
  onClose?: () => void;
}) {
  const pathname = usePathname();
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
  const { data: dashboard } = useQuery({
    queryKey: ['dashboard', 'sidebar'],
    queryFn: () => apiRequest<Dashboard>('/dashboard'),
    staleTime: 60_000,
    retry: false,
  });

  const content = (
    <div className="flex h-full flex-col bg-ink-950 text-white">
      <div className="flex h-[72px] items-center justify-between px-5">
        <Link href="/" onClick={onClose}>
          <Brand light />
        </Link>
        <Button
          variant="ghost"
          size="icon"
          className="text-ink-300 hover:bg-white/10 hover:text-white lg:hidden"
          onClick={onClose}
          aria-label="Close menu"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="mx-4 mt-2 rounded-2xl border border-white/10 bg-white/[0.045] px-3.5 py-3">
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-ink-400">
          Workspace
        </p>
        <div className="mt-1.5 flex items-center justify-between gap-2">
          <p className="truncate text-[13px] font-semibold text-white">
            {businessName ?? 'Your business'}
          </p>
          <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-brand-300" />
        </div>
      </div>

      <nav className="mt-5 flex-1 space-y-1 overflow-y-auto px-3 scrollbar-thin">
        {navigation.map((item) => {
          const active = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
          const Icon = item.icon;
          const count =
            item.badge === 'review'
              ? summary?.needs_review
              : item.badge === 'disputes'
                ? disputeStats?.open
                : undefined;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onClose}
              className={cn('sidebar-link', active && 'sidebar-link-active')}
            >
              <Icon className="h-[18px] w-[18px] shrink-0" />
              <span className="flex-1">{item.label}</span>
              {count ? (
                <span
                  className={cn(
                    'rounded-full px-1.5 py-0.5 text-[10px] font-bold tabular-nums',
                    item.badge === 'disputes'
                      ? 'bg-red-500/20 text-red-300'
                      : 'bg-brand-500/20 text-brand-300',
                  )}
                >
                  {count}
                </span>
              ) : null}
            </Link>
          );
        })}

        <div className="pt-4">
          <Link
            href="/fulfillments/new"
            onClick={onClose}
            className="group flex items-center gap-3 rounded-xl border border-brand-400/30 bg-brand-500/10 px-3 py-3 transition hover:border-brand-400/60 hover:bg-brand-500/20"
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-500 text-white">
              <Camera className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <p className="text-[13px] font-semibold text-white">Log fulfillment</p>
              <p className="text-[11px] text-brand-300">Capture evidence now</p>
            </div>
          </Link>
        </div>
      </nav>

      <div className="border-t border-white/10 p-3">
        <Link
          href="/settings"
          onClick={onClose}
          className={cn('sidebar-link', pathname.startsWith('/settings') && 'sidebar-link-active')}
        >
          <Settings className="h-[18px] w-[18px]" />
          Settings
        </Link>
        <div className="mt-2 flex items-center justify-between rounded-xl bg-white/[0.04] px-3 py-2.5">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-400">
              Trust state
            </p>
            <p className="mt-0.5 text-[12px] font-semibold text-white">
              {dashboard?.trust?.label ?? 'Not computed'}
            </p>
          </div>
          <Badge
            tone={
              dashboard?.trust?.state === 'verified'
                ? 'success'
                : dashboard?.trust?.state === 'review'
                  ? 'danger'
                  : 'warning'
            }
          >
            {dashboard?.trust?.state ?? 'new'}
          </Badge>
        </div>
      </div>
    </div>
  );

  return (
    <>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 lg:block">{content}</aside>
      {mobileOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-ink-950/60 backdrop-blur-sm"
            onClick={onClose}
            aria-label="Close menu"
          />
          <aside className="relative h-full w-[280px] shadow-float">{content}</aside>
        </div>
      ) : null}
    </>
  );
}
