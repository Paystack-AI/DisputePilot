'use client';

import { useDeferredValue, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeftRight,
  Bell,
  ChevronDown,
  LogOut,
  Menu,
  Search,
  Settings,
  ShieldCheck,
  ShoppingBag,
  UserRound,
} from 'lucide-react';
import { apiList, apiRequest, logOutMerchant } from '@/lib/api';
import { formatMoney } from '@/lib/format';
import type { CustomerSummary, DisputeStats, Merchant, Order } from '@/lib/types';
import { useAuthStore } from '@/stores/auth';
import { Avatar } from '@/components/ui/avatar';
import { ThemeToggle } from '@/components/theme-toggle';

export function Topbar({ onMenu }: { onMenu: () => void }) {
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

  const logout = async () => {
    try {
      await apiRequest('/auth/logout', { method: 'POST', noRedirect: true });
    } catch {
      // the local session is cleared regardless
    }
    logOutMerchant();
    clearSession();
    queryClient.clear();
    router.replace('/login');
  };

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-line bg-surface px-4 sm:px-6 lg:px-8">
      <button
        type="button"
        className="rounded-lg p-2 text-ink-500 hover:bg-ink-100 lg:hidden"
        onClick={onMenu}
        aria-label="Open menu"
      >
        <Menu className="h-5 w-5" />
      </button>

      <GlobalSearch />

      <div className="ml-auto flex items-center gap-1">
        <ThemeToggle />
        <Link
          href="/disputes?status=pending"
          className="relative flex h-9 w-9 items-center justify-center rounded-lg text-ink-500 transition hover:bg-ink-100 hover:text-ink-900"
          aria-label={stats?.open ? `${stats.open} open disputes` : 'Disputes'}
          title={stats?.open ? `${stats.open} open disputes` : 'Disputes'}
        >
          <Bell className="h-[18px] w-[18px]" />
          {stats?.open ? (
            <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-red-500 ring-2 ring-surface" />
          ) : null}
        </Link>

        <div className="relative ml-1" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            className="flex items-center gap-2 rounded-lg py-1 pl-1 pr-2 transition hover:bg-ink-100"
            aria-expanded={menuOpen}
          >
            <Avatar name={merchant?.business_name} size="sm" />
            <span className="hidden max-w-[140px] truncate text-[13px] font-medium text-ink-900 sm:block">
              {merchant?.business_name ?? 'Your business'}
            </span>
            <ChevronDown className="h-3.5 w-3.5 text-ink-400" />
          </button>

          {menuOpen ? (
            <div className="absolute right-0 top-11 w-60 overflow-hidden rounded-lg border border-line bg-surface shadow-float">
              <div className="border-b border-line px-3.5 py-3">
                <p className="truncate text-[13px] font-medium text-ink-900">
                  {merchant?.business_name}
                </p>
                <p className="truncate text-[12px] text-ink-500">
                  {merchant?.email ?? merchant?.google_email ?? 'Merchant account'}
                </p>
              </div>
              <div className="p-1">
                {[
                  { href: '/settings/account', icon: UserRound, label: 'Account' },
                  { href: '/settings', icon: Settings, label: 'Settings' },
                  { href: '/trust', icon: ShieldCheck, label: 'Trust profile' },
                ].map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setMenuOpen(false)}
                    className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] text-ink-700 hover:bg-ink-100"
                  >
                    <item.icon className="h-4 w-4 text-ink-400" /> {item.label}
                  </Link>
                ))}
              </div>
              <div className="border-t border-line p-1">
                <button
                  type="button"
                  onClick={logout}
                  className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-[13px] text-red-600 hover:bg-red-50"
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

/** Finds orders and customers as you type; a payment reference opens the transaction */
function GlobalSearch() {
  const router = useRouter();
  const [value, setValue] = useState('');
  const [open, setOpen] = useState(false);
  const query = useDeferredValue(value.trim());
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const enabled = open && query.length >= 2;
  const orders = useQuery({
    queryKey: ['search', 'orders', query],
    queryFn: () => apiList<Order>(`/orders?limit=5&search=${encodeURIComponent(query)}`),
    enabled,
    staleTime: 30_000,
  });
  const customers = useQuery({
    queryKey: ['search', 'customers', query],
    queryFn: () =>
      apiList<CustomerSummary>(`/customers?limit=5&search=${encodeURIComponent(query)}`),
    enabled,
    staleTime: 30_000,
  });

  const go = (href: string) => {
    setOpen(false);
    setValue('');
    router.push(href);
  };

  const orderRows = orders.data?.data ?? [];
  const customerRows = customers.data?.data ?? [];
  const loading = orders.isFetching || customers.isFetching;

  return (
    <div ref={boxRef} className="relative min-w-0 flex-1 sm:max-w-md">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
      <input
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setOpen(false);
          if (event.key === 'Enter' && query) {
            const first = orderRows[0] ?? null;
            if (first) go(`/orders/${first.id}`);
            else go(`/transactions/${encodeURIComponent(query)}`);
          }
        }}
        placeholder="Search orders, customers or a payment reference"
        className="h-9 w-full rounded-lg border border-line bg-ink-50 pl-9 pr-3 text-[13px] text-ink-900 outline-none transition placeholder:text-ink-400 focus:border-brand-500 focus:bg-surface focus:ring-[3px] focus:ring-brand-500/15"
        aria-label="Search"
      />

      {open && query.length >= 2 ? (
        <div className="absolute left-0 right-0 top-11 z-30 overflow-hidden rounded-lg border border-line bg-surface shadow-float">
          {orderRows.length ? (
            <Group label="Orders">
              {orderRows.map((order) => (
                <Row
                  key={order.id}
                  icon={<ShoppingBag className="h-4 w-4" />}
                  title={`Order ${order.order_number ?? '(no number)'}`}
                  meta={order.customer?.name ?? order.customer?.email ?? order.description ?? ''}
                  right={formatMoney(order.amount, order.currency)}
                  onClick={() => go(`/orders/${order.id}`)}
                />
              ))}
            </Group>
          ) : null}
          {customerRows.length ? (
            <Group label="Customers">
              {customerRows.map((customer) => (
                <Row
                  key={customer.id}
                  icon={<UserRound className="h-4 w-4" />}
                  title={customer.name ?? customer.email ?? 'Unnamed customer'}
                  meta={customer.name ? (customer.email ?? '') : ''}
                  right={`${customer.payment_count} payments`}
                  onClick={() => go(`/customers/${customer.id}`)}
                />
              ))}
            </Group>
          ) : null}
          <Group label="Payment">
            <Row
              icon={<ArrowLeftRight className="h-4 w-4" />}
              title={`Open payment ${query}`}
              meta="By Paystack reference"
              onClick={() => go(`/transactions/${encodeURIComponent(query)}`)}
            />
          </Group>
          {loading && !orderRows.length && !customerRows.length ? (
            <p className="px-3 pb-3 text-[12px] text-ink-400">Searching…</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="border-b border-line py-1 last:border-b-0">
      <p className="px-3 pb-1 pt-1.5 text-[11px] font-medium text-ink-400">{label}</p>
      {children}
    </div>
  );
}

function Row({
  icon,
  title,
  meta,
  right,
  onClick,
}: {
  icon: React.ReactNode;
  title: string;
  meta?: string;
  right?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-ink-100"
    >
      <span className="text-ink-400">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] text-ink-900">{title}</span>
        {meta ? <span className="block truncate text-[11px] text-ink-500">{meta}</span> : null}
      </span>
      {right ? <span className="text-[12px] tabular-nums text-ink-500">{right}</span> : null}
    </button>
  );
}
