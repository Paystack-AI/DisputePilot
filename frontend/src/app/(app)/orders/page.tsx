'use client';

import { useDeferredValue, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { href, rowClick } from '@/lib/links';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Plus, Search, ShoppingBag } from 'lucide-react';
import { apiList } from '@/lib/api';
import { formatMoney, timeAgo, titleCase } from '@/lib/format';
import type { Order, PageMeta } from '@/lib/types';
import { ORDER_STATUS_LABELS } from '@/lib/constants';
import { PageHeader } from '@/components/ui/page-header';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge, statusTone } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { Pagination } from '@/components/ui/pagination';
import { PageSkeleton } from '@/components/ui/skeleton';
import { Tabs } from '@/components/ui/tabs';
import { useUrlParam } from '@/lib/use-url-param';

const statusFilters = ['all', 'pending', 'paid', 'fulfilled', 'cancelled'];

export default function OrdersPage() {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search);
  const [status, setStatus] = useUrlParam('status', 'all');
  const [page, setPage] = useState(1);

  const ordersQuery = useQuery({
    queryKey: ['orders', 'list', deferredSearch, status, page],
    queryFn: () =>
      apiList<Order>(
        `/orders?limit=20&page=${page}${deferredSearch ? `&search=${encodeURIComponent(deferredSearch)}` : ''}${status !== 'all' ? `&status=${status}` : ''}`,
      ),
  });

  const meta: PageMeta | undefined = ordersQuery.data?.meta;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Sales ledger"
        title="Orders"
        description="Every sale you expect, linked to the payment that settles it."
        actions={
          <Link href="/orders/new">
            <Button>
              <Plus className="h-4 w-4" /> New order
            </Button>
          </Link>
        }
      />

      <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
        <Tabs
          items={statusFilters.map((value) => ({
            value,
            label:
              value === 'all'
                ? 'All'
                : ORDER_STATUS_LABELS[value as keyof typeof ORDER_STATUS_LABELS],
          }))}
          value={status}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
        />
        <div className="relative w-full max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
          <Input
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            placeholder="Search order, customer or description"
            className="pl-9"
          />
        </div>
      </div>

      {ordersQuery.isLoading ? (
        <PageSkeleton />
      ) : ordersQuery.data?.data.length ? (
        <div className="table-shell overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th>Order</th>
                <th>Customer</th>
                <th>Amount</th>
                <th>Source</th>
                <th>Status</th>
                <th>Payment</th>
                <th>Placed</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {ordersQuery.data.data.map((order) => (
                <tr
                  key={order.id}
                  className="row-link"
                  onClick={rowClick(router.push, href.order(order.id))}
                >
                  <td>
                    <Link
                      href={`/orders/${order.id}`}
                      className="font-semibold text-ink-900 hover:text-brand-700"
                    >
                      {order.order_number ?? 'No number'}
                    </Link>
                    <p className="mt-0.5 max-w-[240px] truncate text-[11px] text-ink-400">
                      {order.description ?? 'No description'}
                    </p>
                  </td>
                  <td>
                    {order.customer ? (
                      <Link
                        href={`/customers/${order.customer.id}`}
                        className="block text-[12px] font-medium text-ink-800 hover:text-brand-600 hover:underline"
                      >
                        {order.customer.name ?? order.customer.email ?? 'Customer'}
                      </Link>
                    ) : (
                      <p className="text-[12px] font-medium text-ink-800">—</p>
                    )}
                    <p className="text-[11px] text-ink-400">
                      {order.customer?.email ?? 'No customer'}
                    </p>
                  </td>
                  <td className="font-semibold text-ink-900">
                    {formatMoney(order.amount, order.currency)}
                  </td>
                  <td className="text-[12px] capitalize text-ink-500">{titleCase(order.source)}</td>
                  <td>
                    <Badge tone={statusTone(order.status)}>
                      {ORDER_STATUS_LABELS[order.status]}
                    </Badge>
                  </td>
                  <td>
                    {order.is_linked ? (
                      <Badge tone="success">Linked</Badge>
                    ) : order.resolution ? (
                      <Badge tone="neutral">{titleCase(order.resolution)}</Badge>
                    ) : (
                      <span className="text-[11px] text-ink-400">Awaiting</span>
                    )}
                  </td>
                  <td className="text-[12px] text-ink-500">{timeAgo(order.ordered_at)}</td>
                  <td>
                    <Link href={`/orders/${order.id}`}>
                      <Button variant="ghost" size="sm">
                        <ArrowRight className="h-3.5 w-3.5" />
                      </Button>
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination meta={meta} onPageChange={setPage} />
        </div>
      ) : (
        <EmptyState
          icon={<ShoppingBag className="h-5 w-5" />}
          title={deferredSearch || status !== 'all' ? 'No matching orders' : 'No orders yet'}
          description="Create orders as sales happen so reconciliation can match them to payments."
          action={
            <Link href="/orders/new">
              <Button>
                <Plus className="h-4 w-4" /> New order
              </Button>
            </Link>
          }
        />
      )}
    </div>
  );
}
