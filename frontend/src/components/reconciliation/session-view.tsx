'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import {
  BadgeCheck,
  Check,
  CircleSlash2,
  Flag,
  Link2,
  Plus,
  Search,
  ShieldAlert,
  X,
} from 'lucide-react';
import { apiList } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDate, formatMoney, timeAgo, titleCase } from '@/lib/format';
import type { Order, ReconciliationView, Transaction } from '@/lib/types';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Modal } from '@/components/ui/modal';
import { Input } from '@/components/ui/input';
import { Tabs } from '@/components/ui/tabs';

type Actions = {
  onAccept?: (transactionId: string, orderId: string) => void;
  onReject?: (transactionId: string, orderId: string) => void;
  onLinkOrder?: (transaction: Transaction, order: Order) => void;
  onResolveOrder?: (orderId: string, resolution: 'cash_payment' | 'payment_failed') => void;
  onUnflagTransaction?: (reference: string) => void;
  onUnflagOrder?: (orderId: string) => void;
  busyKey?: string | null;
};

export function ReconciliationSessionView({
  view,
  actions,
  readOnly = false,
}: {
  view: ReconciliationView;
  actions?: Actions;
  readOnly?: boolean;
}) {
  const [tab, setTab] = useState('all');
  const [linking, setLinking] = useState<Transaction | null>(null);
  const totals = view.session.totals;
  const active = view.session.status === 'in_progress';

  const tabs = [
    { value: 'all', label: 'All', count: totals.total_transactions },
    { value: 'matched', label: 'Matched', count: totals.matched },
    { value: 'suggested', label: 'Suggested', count: totals.suggested },
    {
      value: 'unmatched',
      label: 'Unmatched',
      count: totals.unmatched_payments + totals.unmatched_orders,
    },
    {
      value: 'flagged',
      label: 'Flagged',
      count: totals.flagged + (view.flagged_orders.length || 0),
    },
  ];

  return (
    <div className="space-y-5">
      <div className="surface overflow-hidden">
        <div className="flex flex-col gap-4 border-b border-line px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[17px] font-semibold tracking-[-0.02em] text-ink-900">
                {formatDate(view.session.date_range_start)} –{' '}
                {formatDate(view.session.date_range_end)}
              </h2>
              <Badge tone={active ? 'warning' : 'success'} dot>
                {active ? 'In progress' : 'Completed'}
              </Badge>
            </div>
            <p className="mt-1 text-[12px] text-ink-500">
              {active
                ? 'Review matches and clear exceptions before completing the session.'
                : view.session.completed_at
                  ? `Completed ${timeAgo(view.session.completed_at)}`
                  : 'Reconciliation session'}
            </p>
          </div>
          <Tabs items={tabs} value={tab} onChange={setTab} />
        </div>

        <div className="px-5 py-4">
          {tab === 'all' ? <AllTransactions view={view} /> : null}
          {tab === 'matched' ? (
            <MatchedList view={view} actions={actions} readOnly={readOnly} />
          ) : null}
          {tab === 'suggested' ? (
            <SuggestionList view={view} actions={actions} readOnly={readOnly} />
          ) : null}
          {tab === 'unmatched' ? (
            <UnmatchedLists view={view} actions={actions} readOnly={readOnly} onLink={setLinking} />
          ) : null}
          {tab === 'flagged' ? (
            <FlaggedList view={view} actions={actions} readOnly={readOnly} />
          ) : null}
        </div>
      </div>

      <LinkOrderModal
        transaction={linking}
        onClose={() => setLinking(null)}
        onSelect={(order) => {
          if (linking && actions?.onLinkOrder) actions.onLinkOrder(linking, order);
          setLinking(null);
        }}
      />
    </div>
  );
}

function AllTransactions({ view }: { view: ReconciliationView }) {
  const rows = useMemo(() => {
    const items: {
      key: string;
      transaction: Transaction;
      orderNumber: string | null;
      state: string;
      tone: 'success' | 'warning' | 'danger' | 'neutral';
    }[] = [];
    view.matched.forEach((item) =>
      items.push({
        key: `m-${item.transaction.id}`,
        transaction: item.transaction,
        orderNumber: item.order.order_number,
        state: item.tier ? `Matched · tier ${item.tier}` : 'Matched manually',
        tone: 'success',
      }),
    );
    view.suggestions.forEach((item) =>
      items.push({
        key: `s-${item.id}`,
        transaction: item.transaction,
        orderNumber: item.order.order_number,
        state: `${item.likelihood_percent}% suggested`,
        tone: 'warning',
      }),
    );
    view.unmatched_payments.forEach((transaction) =>
      items.push({
        key: `u-${transaction.id}`,
        transaction,
        orderNumber: null,
        state: 'Unmatched payment',
        tone: 'warning',
      }),
    );
    view.flagged.forEach((item) =>
      items.push({
        key: `f-${item.transaction.id}`,
        transaction: item.transaction,
        orderNumber: null,
        state: 'Flagged',
        tone: 'danger',
      }),
    );
    return items.sort(
      (a, b) =>
        new Date(b.transaction.paid_at ?? b.transaction.created_at).getTime() -
        new Date(a.transaction.paid_at ?? a.transaction.created_at).getTime(),
    );
  }, [view]);

  if (!rows.length) {
    return (
      <EmptyState
        icon={<CircleSlash2 className="h-5 w-5" />}
        title="No payments in this range"
        description="Start a session for a period with successful Paystack payments."
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="table-base">
        <thead>
          <tr>
            <th>Paystack reference</th>
            <th>Customer</th>
            <th>Amount</th>
            <th>Order</th>
            <th>Status</th>
            <th>Paid</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>
                <p className="font-mono text-[12px] font-semibold text-ink-900">
                  {row.transaction.reference}
                </p>
                <p className="mt-0.5 text-[11px] capitalize text-ink-400">
                  {row.transaction.channel.replace(/_/g, ' ')}
                </p>
              </td>
              <td>
                <p className="text-[12px] font-medium text-ink-800">
                  {row.transaction.customer_name ?? 'Unknown customer'}
                </p>
                <p className="text-[11px] text-ink-400">{row.transaction.customer_email ?? '—'}</p>
              </td>
              <td className="font-semibold text-ink-900">
                {formatMoney(row.transaction.amount, row.transaction.currency)}
              </td>
              <td>{row.orderNumber ?? '—'}</td>
              <td>
                <Badge tone={row.tone}>{row.state}</Badge>
              </td>
              <td className="text-[12px] text-ink-500">
                {row.transaction.paid_at ? timeAgo(row.transaction.paid_at) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MatchedList({
  view,
  actions,
  readOnly,
}: {
  view: ReconciliationView;
  actions?: Actions;
  readOnly: boolean;
}) {
  if (!view.matched.length) {
    return (
      <EmptyState
        icon={<BadgeCheck className="h-5 w-5" />}
        title="No matched payments"
        description="Accept a suggestion or link a payment to move it here."
      />
    );
  }

  return (
    <div className="divide-y divide-line">
      {view.matched.map((item) => (
        <div
          key={item.transaction.id}
          className="flex flex-col gap-3 rounded-xl bg-brand-50/50 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-[13px] font-semibold text-ink-900">
                {formatMoney(item.transaction.amount, item.transaction.currency)}
              </p>
              <Badge tone="success">
                {item.tier ? `Tier ${item.tier} match` : 'Manually matched'}
              </Badge>
              {item.confidence !== null ? (
                <span className="text-[11px] text-ink-500">{item.confidence}% confidence</span>
              ) : null}
            </div>
            <p className="mt-1 text-[12px] text-ink-500">
              {item.transaction.reference} → Order {item.order.order_number ?? '—'} ·{' '}
              {item.transaction.customer_name ?? item.transaction.customer_email ?? 'Customer'}
            </p>
          </div>
          {!readOnly && actions?.onReject ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => actions.onReject?.(item.transaction.id, item.order.id)}
              loading={actions.busyKey === `reject-${item.transaction.id}`}
            >
              Undo match
            </Button>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function SuggestionList({
  view,
  actions,
  readOnly,
}: {
  view: ReconciliationView;
  actions?: Actions;
  readOnly: boolean;
}) {
  if (!view.suggestions.length) {
    return (
      <EmptyState
        icon={<Link2 className="h-5 w-5" />}
        title="No suggestions waiting"
        description="The matcher found no uncertain pairs in this session."
      />
    );
  }

  return (
    <div className="space-y-3">
      {view.suggestions.map((item) => (
        <div key={item.id} className="rounded-2xl border border-amber-200 bg-amber-50/40 p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Badge tone={item.confidence_tier === 'likely' ? 'success' : 'warning'}>
                {item.likelihood_percent}% {item.confidence_tier}
              </Badge>
              <p className="text-[12px] text-ink-500">{item.reasoning}</p>
            </div>
            <span className="text-[11px] text-ink-400">Tier {item.tier}</span>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-xl border border-line bg-white p-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-400">
                Payment
              </p>
              <p className="mt-1 text-[14px] font-semibold text-ink-900">
                {formatMoney(item.transaction.amount, item.transaction.currency)}
              </p>
              <p className="mt-0.5 font-mono text-[11px] text-ink-500">
                {item.transaction.reference}
              </p>
              <p className="mt-1 text-[11px] text-ink-400">
                {item.transaction.customer_name ?? item.transaction.customer_email ?? 'Unknown'}
              </p>
            </div>
            <div className="rounded-xl border border-line bg-white p-3">
              <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-400">
                Order
              </p>
              <p className="mt-1 text-[14px] font-semibold text-ink-900">
                {formatMoney(item.order.amount, item.order.currency)}
              </p>
              <p className="mt-0.5 text-[11px] text-ink-500">
                {item.order.order_number ?? 'No order number'}
              </p>
              <p className="mt-1 truncate text-[11px] text-ink-400">
                {item.order.description ?? item.order.customer?.name ?? '—'}
              </p>
            </div>
          </div>
          {!readOnly ? (
            <div className="mt-3 flex items-center justify-end gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => actions?.onReject?.(item.transaction.id, item.order.id)}
                loading={actions?.busyKey === `reject-${item.transaction.id}`}
              >
                <X className="h-3.5 w-3.5" /> Not a match
              </Button>
              <Button
                size="sm"
                onClick={() => actions?.onAccept?.(item.transaction.id, item.order.id)}
                loading={actions?.busyKey === `accept-${item.transaction.id}`}
              >
                <Check className="h-3.5 w-3.5" /> Accept match
              </Button>
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function UnmatchedLists({
  view,
  actions,
  readOnly,
  onLink,
}: {
  view: ReconciliationView;
  actions?: Actions;
  readOnly: boolean;
  onLink: (transaction: Transaction) => void;
}) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-[13px] font-semibold text-ink-900">Payments without orders</h3>
          <Badge tone="warning">{view.unmatched_payments.length}</Badge>
        </div>
        {view.unmatched_payments.length ? (
          <div className="space-y-2.5">
            {view.unmatched_payments.map((transaction) => (
              <div key={transaction.id} className="rounded-xl border border-line bg-white p-3.5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[13px] font-semibold text-ink-900">
                      {formatMoney(transaction.amount, transaction.currency)}
                    </p>
                    <p className="mt-0.5 font-mono text-[11px] text-ink-500">
                      {transaction.reference}
                    </p>
                    <p className="mt-1 text-[11px] text-ink-400">
                      {transaction.customer_name ??
                        transaction.customer_email ??
                        'Unknown customer'}
                    </p>
                  </div>
                  {!readOnly ? (
                    <div className="flex shrink-0 gap-1.5">
                      <Button variant="outline" size="sm" onClick={() => onLink(transaction)}>
                        <Link2 className="h-3.5 w-3.5" /> Link
                      </Button>
                      <Link
                        href={`/orders/new?amount=${transaction.amount}&reference=${encodeURIComponent(transaction.reference)}&email=${encodeURIComponent(transaction.customer_email ?? '')}`}
                      >
                        <Button variant="ghost" size="sm" aria-label="Create order">
                          <Plus className="h-3.5 w-3.5" />
                        </Button>
                      </Link>
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-xl bg-ink-50 px-4 py-6 text-center text-[12px] text-ink-400">
            Every payment is linked
          </p>
        )}
      </div>

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-[13px] font-semibold text-ink-900">Orders without payments</h3>
          <Badge tone="neutral">{view.unmatched_orders.length}</Badge>
        </div>
        {view.unmatched_orders.length ? (
          <div className="space-y-2.5">
            {view.unmatched_orders.map((order) => (
              <div key={order.id} className="rounded-xl border border-line bg-white p-3.5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-[13px] font-semibold text-ink-900">
                      {formatMoney(order.amount, order.currency)}
                    </p>
                    <p className="mt-0.5 text-[11px] text-ink-500">
                      Order {order.order_number ?? '—'} · {order.customer?.name ?? 'No customer'}
                    </p>
                    <p className="mt-1 truncate text-[11px] text-ink-400">
                      {order.description ?? '—'}
                    </p>
                  </div>
                  {!readOnly ? (
                    <div className="flex shrink-0 gap-1.5">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => actions?.onResolveOrder?.(order.id, 'cash_payment')}
                      >
                        Mark cash
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => actions?.onResolveOrder?.(order.id, 'payment_failed')}
                      >
                        Failed
                      </Button>
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-xl bg-ink-50 px-4 py-6 text-center text-[12px] text-ink-400">
            Every order is settled
          </p>
        )}
      </div>
    </div>
  );
}

function FlaggedList({
  view,
  actions,
  readOnly,
}: {
  view: ReconciliationView;
  actions?: Actions;
  readOnly: boolean;
}) {
  const empty = !view.flagged.length && !view.flagged_orders.length;
  if (empty) {
    return (
      <EmptyState
        icon={<Flag className="h-5 w-5" />}
        title="No flagged items"
        description="Anomalies from the matcher will appear here for review."
      />
    );
  }

  return (
    <div className="space-y-2.5">
      {view.flagged.map((item) => (
        <div
          key={item.transaction.id}
          className="rounded-xl border border-red-200 bg-red-50/40 p-4"
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-red-100 text-red-600">
                <ShieldAlert className="h-4 w-4" />
              </div>
              <div>
                <p className="text-[13px] font-semibold text-ink-900">
                  {formatMoney(item.transaction.amount, item.transaction.currency)} ·{' '}
                  {item.transaction.reference}
                </p>
                <p className="mt-0.5 text-[11px] text-red-700">
                  {item.reason ?? 'Flagged for review'}
                </p>
              </div>
            </div>
            {!readOnly ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => actions?.onUnflagTransaction?.(item.transaction.reference)}
              >
                Dismiss flag
              </Button>
            ) : null}
          </div>
        </div>
      ))}
      {view.flagged_orders.map((item) => (
        <div key={item.order.id} className="rounded-xl border border-red-200 bg-red-50/40 p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-red-100 text-red-600">
                <ShieldAlert className="h-4 w-4" />
              </div>
              <div>
                <p className="text-[13px] font-semibold text-ink-900">
                  Order {item.order.order_number ?? '—'} ·{' '}
                  {formatMoney(item.order.amount, item.order.currency)}
                </p>
                <p className="mt-0.5 text-[11px] text-red-700">{item.reason ?? 'Flagged order'}</p>
              </div>
            </div>
            {!readOnly ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => actions?.onUnflagOrder?.(item.order.id)}
              >
                Dismiss flag
              </Button>
            ) : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function LinkOrderModal({
  transaction,
  onClose,
  onSelect,
}: {
  transaction: Transaction | null;
  onClose: () => void;
  onSelect: (order: Order) => void;
}) {
  const [search, setSearch] = useState('');
  const { data } = useQuery({
    queryKey: ['orders', 'link-search', search],
    queryFn: () =>
      apiList<Order>(`/orders?search=${encodeURIComponent(search)}&limit=8&status=pending`),
    enabled: Boolean(transaction),
  });
  const orders = data?.data ?? [];

  return (
    <Modal
      open={Boolean(transaction)}
      onClose={onClose}
      title="Link payment to an order"
      description={
        transaction
          ? `${formatMoney(transaction.amount, transaction.currency)} from ${transaction.customer_name ?? transaction.customer_email ?? 'customer'}`
          : undefined
      }
    >
      <div className="space-y-4">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
          <Input
            autoFocus
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search order number, description or customer"
            className="pl-9"
          />
        </div>
        <div className="max-h-80 space-y-2 overflow-y-auto scrollbar-thin">
          {orders.length ? (
            orders.map((order) => (
              <button
                key={order.id}
                type="button"
                onClick={() => onSelect(order)}
                className="flex w-full items-center justify-between gap-3 rounded-xl border border-line px-3.5 py-3 text-left transition hover:border-brand-300 hover:bg-brand-50/50"
              >
                <div>
                  <p className="text-[13px] font-semibold text-ink-900">
                    Order {order.order_number ?? '—'}
                  </p>
                  <p className="mt-0.5 text-[11px] text-ink-500">
                    {order.customer?.name ?? order.customer?.email ?? 'No customer'} ·{' '}
                    {titleCase(order.status)}
                  </p>
                </div>
                <span className="text-[13px] font-semibold text-ink-900">
                  {formatMoney(order.amount, order.currency)}
                </span>
              </button>
            ))
          ) : (
            <p className="py-8 text-center text-[12px] text-ink-400">No pending orders found</p>
          )}
        </div>
        <div className="flex justify-end">
          <Link href="/orders/new">
            <Button variant="outline" size="sm">
              <Plus className="h-3.5 w-3.5" /> Create an order
            </Button>
          </Link>
        </div>
      </div>
    </Modal>
  );
}
