'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeft,
  ArrowRight,
  CalendarClock,
  Camera,
  CircleDollarSign,
  FileText,
  Gavel,
  Pencil,
  PackageCheck,
  ShoppingBag,
  Users,
} from 'lucide-react';
import { apiList, apiRequest } from '@/lib/api';
import { formatDate, formatDateTime, formatMoney, percent, timeAgo, titleCase } from '@/lib/format';
import type { Customer, DisputeSummary, LedgerEntry, Order, TransactionSummary } from '@/lib/types';
import { CATEGORY_LABELS, STATUS_LABELS, TRANSACTION_LABELS } from '@/lib/constants';
import { PageSkeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Avatar } from '@/components/ui/avatar';
import { Badge, statusTone } from '@/components/ui/badge';
import { Tabs } from '@/components/ui/tabs';
import { EmptyState } from '@/components/ui/empty-state';
import { PageHeader } from '@/components/ui/page-header';
import { CustomerEditModal } from '@/components/customers/customer-edit-modal';

const ledgerIcons = {
  payment: CircleDollarSign,
  order: ShoppingBag,
  dispute: Gavel,
  fulfillment: Camera,
};

export default function CustomerLedgerPage() {
  const params = useParams<{ id: string }>();
  const [tab, setTab] = useState('timeline');
  const [editing, setEditing] = useState(false);

  const customerQuery = useQuery({
    queryKey: ['customer', params.id],
    queryFn: () => apiRequest<Customer>(`/customers/${params.id}`),
    enabled: Boolean(params.id),
  });
  const ledgerQuery = useQuery({
    queryKey: ['customer', params.id, 'ledger'],
    queryFn: () => apiList<LedgerEntry>(`/customers/${params.id}/ledger?limit=40`),
    enabled: Boolean(params.id),
  });
  const transactionsQuery = useQuery({
    queryKey: ['customer', params.id, 'transactions'],
    queryFn: () => apiList<TransactionSummary>(`/customers/${params.id}/transactions?limit=30`),
    enabled: Boolean(params.id),
  });
  const disputesQuery = useQuery({
    queryKey: ['customer', params.id, 'disputes'],
    queryFn: () => apiList<DisputeSummary>(`/customers/${params.id}/disputes?limit=20`),
    enabled: Boolean(params.id),
  });
  const ordersQuery = useQuery({
    queryKey: ['customer', params.id, 'orders'],
    queryFn: () => apiList<Order>(`/customers/${params.id}/orders?limit=20`),
    enabled: Boolean(params.id),
  });

  if (customerQuery.isLoading) return <PageSkeleton />;
  if (customerQuery.isError || !customerQuery.data) {
    return (
      <div className="space-y-5">
        <Link href="/customers">
          <Button variant="outline">
            <ArrowLeft className="h-4 w-4" /> Back to customers
          </Button>
        </Link>
        <Alert tone="danger" title="Could not load this customer">
          {customerQuery.error instanceof Error ? customerQuery.error.message : 'Please try again.'}
        </Alert>
      </div>
    );
  }

  const customer = customerQuery.data;
  const stats = customer.stats;

  return (
    <div className="space-y-6">
      <Link
        href="/customers"
        className="inline-flex items-center gap-2 text-[12px] font-semibold text-ink-500 hover:text-ink-800"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> All customers
      </Link>

      <PageHeader
        eyebrow="Customer ledger"
        title={customer.name ?? customer.email ?? 'Unnamed customer'}
        description={customer.email ?? 'No email on file'}
        actions={
          <>
            <Button variant="ghost" onClick={() => setEditing(true)}>
              <Pencil className="h-4 w-4" /> Edit
            </Button>
            <Link
              href={`/orders/new?customer=${customer.id}${customer.email ? `&email=${encodeURIComponent(customer.email)}` : ''}`}
            >
              <Button variant="outline">
                <PackageCheck className="h-4 w-4" /> Create order
              </Button>
            </Link>
            <Link
              href={`/fulfillments/new${customer.name ? `?customer=${encodeURIComponent(customer.name)}` : ''}`}
            >
              <Button>
                <Camera className="h-4 w-4" /> Log fulfillment
              </Button>
            </Link>
          </>
        }
      />

      <div className="surface p-5">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <Avatar name={customer.name ?? customer.email} size="lg" />
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-semibold tracking-[-0.03em] text-ink-950">
                  {customer.name ?? 'Unnamed customer'}
                </h2>
                {customer.is_shared ? <Badge tone="info">Shared email</Badge> : null}
                {stats.dispute_count ? (
                  <Badge tone="danger">
                    {stats.dispute_count} dispute{stats.dispute_count === 1 ? '' : 's'}
                  </Badge>
                ) : (
                  <Badge tone="success">No disputes</Badge>
                )}
              </div>
              <p className="mt-1 text-[13px] text-ink-500">
                {customer.email ?? 'No email'} {customer.phone ? `· ${customer.phone}` : ''}
              </p>
              <p className="mt-1 text-[11px] text-ink-400">
                First payment {formatDate(stats.first_payment_at)} · Last payment{' '}
                {stats.last_payment_at ? timeAgo(stats.last_payment_at) : '—'}
              </p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Metric label="Payments" value={stats.payment_count} />
            <Metric label="Reconciled" value={percent(stats.reconciled_pct)} />
            <Metric label="Fulfilled" value={stats.fulfilled_count} />
            <Metric label="Dispute rate" value={percent(stats.dispute_rate, 1)} />
          </div>
        </div>
      </div>

      <Tabs
        items={[
          { value: 'timeline', label: 'Timeline', count: ledgerQuery.data?.meta.total },
          { value: 'payments', label: 'Payments', count: transactionsQuery.data?.meta.total },
          { value: 'orders', label: 'Orders', count: ordersQuery.data?.meta.total },
          { value: 'disputes', label: 'Disputes', count: disputesQuery.data?.meta.total },
        ]}
        value={tab}
        onChange={setTab}
        className="w-fit"
      />

      {tab === 'timeline' ? (
        <Card>
          <CardHeader
            title="Relationship timeline"
            description="Every interaction, newest first."
          />
          {ledgerQuery.data?.data.length ? (
            <div className="p-5">
              <div className="relative space-y-5 before:absolute before:bottom-3 before:left-[15px] before:top-3 before:w-px before:bg-line">
                {ledgerQuery.data.data.map((entry) => {
                  const Icon = ledgerIcons[entry.kind];
                  const href =
                    entry.kind === 'order' && entry.order_id
                      ? `/orders/${entry.order_id}`
                      : entry.kind === 'dispute'
                        ? `/disputes/${entry.id}`
                        : entry.kind === 'payment' && entry.reference
                          ? `/transactions/${encodeURIComponent(entry.reference)}`
                          : entry.kind === 'fulfillment'
                            ? `/fulfillments/${entry.id}`
                            : null;
                  return (
                    <div key={`${entry.kind}-${entry.id}`} className="relative flex gap-4">
                      <div className="relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-line bg-white text-ink-500">
                        <Icon className="h-3.5 w-3.5" />
                      </div>
                      <div className="min-w-0 flex-1 rounded-xl border border-line bg-white px-3.5 py-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="text-[12px] font-semibold capitalize text-ink-900">
                              {titleCase(entry.kind)}
                            </p>
                            <Badge tone={statusTone(entry.status)}>{titleCase(entry.status)}</Badge>
                          </div>
                          <span className="text-[10px] text-ink-400">
                            {formatDateTime(entry.occurred_at)}
                          </span>
                        </div>
                        <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
                          <p className="font-mono text-[11px] text-ink-500">
                            {entry.reference ?? '—'}
                          </p>
                          <div className="flex items-center gap-3">
                            {entry.amount !== null && entry.currency ? (
                              <span className="text-[12px] font-semibold text-ink-900">
                                {formatMoney(entry.amount, entry.currency)}
                              </span>
                            ) : null}
                            {href ? (
                              <Link
                                href={href}
                                className="text-[11px] font-semibold text-brand-700"
                              >
                                Open
                              </Link>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="p-5">
              <EmptyState
                icon={<CalendarClock className="h-5 w-5" />}
                title="No ledger activity yet"
              />
            </div>
          )}
        </Card>
      ) : null}

      {tab === 'payments' ? (
        <Card>
          <CardHeader
            title="Payment history"
            description="Successful Paystack payments and how they were handled."
          />
          {transactionsQuery.data?.data.length ? (
            <div className="overflow-x-auto">
              <table className="table-base">
                <thead>
                  <tr>
                    <th>Reference</th>
                    <th>Amount</th>
                    <th>Channel</th>
                    <th>Status</th>
                    <th>Reconciliation</th>
                    <th>Paid</th>
                  </tr>
                </thead>
                <tbody>
                  {transactionsQuery.data.data.map((transaction) => (
                    <tr key={transaction.id}>
                      <td className="font-mono text-[12px] font-semibold text-ink-900">
                        <Link
                          href={`/transactions/${encodeURIComponent(transaction.reference)}`}
                          className="hover:text-brand-700"
                        >
                          {transaction.reference}
                        </Link>
                      </td>
                      <td className="font-semibold text-ink-900">
                        {formatMoney(transaction.amount, transaction.currency)}
                      </td>
                      <td className="text-[12px] capitalize text-ink-500">
                        {transaction.channel.replace(/_/g, ' ')}
                      </td>
                      <td>
                        <Badge tone={statusTone(transaction.status)}>
                          {TRANSACTION_LABELS[transaction.status]}
                        </Badge>
                      </td>
                      <td className="text-[12px] text-ink-500">
                        {titleCase(transaction.reconciliation_status)}
                      </td>
                      <td className="text-[12px] text-ink-500">
                        {transaction.paid_at ? formatDateTime(transaction.paid_at) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="p-5">
              <EmptyState icon={<CircleDollarSign className="h-5 w-5" />} title="No payments yet" />
            </div>
          )}
        </Card>
      ) : null}

      {tab === 'orders' ? (
        <Card>
          <CardHeader title="Orders" description="Orders linked to this customer." />
          {ordersQuery.data?.data.length ? (
            <div className="divide-y divide-line">
              {ordersQuery.data.data.map((order) => (
                <Link
                  key={order.id}
                  href={`/orders/${order.id}`}
                  className="flex items-center justify-between gap-3 px-5 py-3.5 transition hover:bg-ink-50/60"
                >
                  <div>
                    <p className="text-[13px] font-semibold text-ink-900">
                      Order {order.order_number ?? '—'}
                    </p>
                    <p className="mt-0.5 text-[11px] text-ink-500">
                      {order.description ?? 'No description'} · {titleCase(order.status)}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-[13px] font-semibold text-ink-900">
                      {formatMoney(order.amount, order.currency)}
                    </span>
                    <ArrowRight className="h-4 w-4 text-ink-400" />
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="p-5">
              <EmptyState icon={<ShoppingBag className="h-5 w-5" />} title="No orders yet" />
            </div>
          )}
        </Card>
      ) : null}

      {tab === 'disputes' ? (
        <Card>
          <CardHeader
            title="Dispute history"
            description="Every claim raised on this customer's payments."
          />
          {disputesQuery.data?.data.length ? (
            <div className="divide-y divide-line">
              {disputesQuery.data.data.map((dispute) => (
                <Link
                  key={dispute.id}
                  href={`/disputes/${dispute.id}`}
                  className="flex flex-col gap-3 px-5 py-4 transition hover:bg-ink-50/60 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="flex items-start gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-red-50 text-red-600">
                      <Gavel className="h-4 w-4" />
                    </div>
                    <div>
                      <p className="text-[13px] font-semibold text-ink-900">
                        {formatMoney(dispute.amount, dispute.currency)} ·{' '}
                        {dispute.category ? CATEGORY_LABELS[dispute.category] : 'Unclassified'}
                      </p>
                      <p className="mt-0.5 text-[11px] text-ink-500">
                        {dispute.transaction_reference} · Opened {timeAgo(dispute.created_at)}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone={statusTone(dispute.status)}>{STATUS_LABELS[dispute.status]}</Badge>
                    <ArrowRight className="h-4 w-4 text-ink-400" />
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="p-5">
              <EmptyState
                icon={<Users className="h-5 w-5" />}
                title="No disputes from this customer"
                description="Their full payment history can still support future evidence."
              />
            </div>
          )}
        </Card>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-3">
        <SmallStat
          icon={<FileText className="h-4 w-4" />}
          label="Orders"
          value={stats.order_count}
        />
        <SmallStat
          icon={<Camera className="h-4 w-4" />}
          label="Fulfilled payments"
          value={stats.fulfilled_count}
        />
        <SmallStat
          icon={<CalendarClock className="h-4 w-4" />}
          label="First seen"
          value={formatDate(customer.first_seen_at)}
        />
      </div>
      {editing ? <CustomerEditModal customer={customer} onClose={() => setEditing(false)} /> : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-400">{label}</p>
      <p className="mt-1 text-xl font-semibold tracking-[-0.03em] text-ink-950">{value}</p>
    </div>
  );
}

function SmallStat({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="surface flex items-center gap-3 px-4 py-3.5">
      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-ink-100 text-ink-500">
        {icon}
      </div>
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-400">{label}</p>
        <p className="text-[13px] font-semibold text-ink-900">{value}</p>
      </div>
    </div>
  );
}
