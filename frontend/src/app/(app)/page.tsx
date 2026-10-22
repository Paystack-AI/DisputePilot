'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  ArrowRight,
  BadgeCheck,
  Camera,
  CheckCircle2,
  CircleDollarSign,
  FileWarning,
  Gavel,
  ListChecks,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  ShoppingBag,
  TrendingUp,
  Users,
} from 'lucide-react';
import { apiRequest } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDate, formatMoney, percent, timeAgo, titleCase } from '@/lib/format';
import type { Dashboard, DisputeStats, DisputeTimeline, ReconciliationHealth } from '@/lib/types';
import {
  CATEGORY_LABELS,
  RECONCILIATION_LABELS,
  STATUS_LABELS,
  TRUST_LABELS,
  TRUST_TONE,
} from '@/lib/constants';
import { PageHeader } from '@/components/ui/page-header';
import { StatCard } from '@/components/ui/stat-card';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge, statusTone } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Countdown } from '@/components/ui/countdown';
import { PageSkeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/ui/empty-state';
import { DisputeChart } from '@/components/dashboard/dispute-chart';
import { ReconciliationChart } from '@/components/dashboard/reconciliation-chart';
import { Avatar } from '@/components/ui/avatar';

const activityIcons = {
  dispute_created: ShieldAlert,
  dispute_submitted: Gavel,
  dispute_won: BadgeCheck,
  dispute_lost: FileWarning,
  dispute_auto_accepted: ShieldAlert,
  fulfillment_logged: Camera,
  reconciliation_completed: CheckCircle2,
  trust_changed: ShieldCheck,
};

export default function DashboardPage() {
  const dashboardQuery = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => apiRequest<Dashboard>('/dashboard'),
    refetchInterval: 60_000,
  });
  const statsQuery = useQuery({
    queryKey: ['disputes', 'stats'],
    queryFn: () => apiRequest<DisputeStats>('/disputes/stats'),
  });
  const timelineQuery = useQuery({
    queryKey: ['dashboard', 'dispute-timeline', 30],
    queryFn: () => apiRequest<DisputeTimeline>('/dashboard/dispute-timeline?days=30'),
  });
  const healthQuery = useQuery({
    queryKey: ['dashboard', 'reconciliation-health', 30],
    queryFn: () => apiRequest<ReconciliationHealth>('/dashboard/reconciliation-health?days=30'),
  });

  if (dashboardQuery.isLoading) return <PageSkeleton />;
  if (dashboardQuery.isError || !dashboardQuery.data) {
    return (
      <div className="space-y-6">
        <PageHeader title="Dashboard" description="Your daily command centre." />
        <EmptyState
          icon={<RefreshCw className="h-5 w-5" />}
          title="We could not load your dashboard"
          description={
            dashboardQuery.error instanceof Error
              ? dashboardQuery.error.message
              : 'Please retry in a moment.'
          }
          action={<Button onClick={() => dashboardQuery.refetch()}>Try again</Button>}
        />
      </div>
    );
  }

  const dashboard = dashboardQuery.data;
  const stats = statsQuery.data;
  const metrics = dashboard.metrics;
  const reconciliation = dashboard.reconciliation;
  const critical = dashboard.critical_dispute;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Today"
        title="Your disputes, under control"
        description="A live view of reconciliation, dispute deadlines and the evidence behind every payment."
        actions={
          <>
            <Link href="/fulfillments/new">
              <Button variant="outline">
                <Camera className="h-4 w-4" /> Log fulfillment
              </Button>
            </Link>
            <Link href="/reconciliation">
              <Button>
                <CheckCircle2 className="h-4 w-4" /> Reconcile payments
              </Button>
            </Link>
          </>
        }
      />

      {critical ? (
        <div className="relative overflow-hidden rounded-2xl bg-ink-950 p-5 text-white shadow-float sm:p-6">
          <div className="absolute -right-16 -top-20 h-64 w-64 rounded-full bg-red-500/20 blur-3xl" />
          <div className="relative flex flex-col justify-between gap-5 sm:flex-row sm:items-center">
            <div className="flex items-start gap-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-red-500/20 text-red-300 ring-1 ring-inset ring-red-400/30">
                <ShieldAlert className="h-5 w-5" />
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-red-300">
                    Dispute requires attention
                  </p>
                  <Countdown
                    dueAt={critical.due_at}
                    serverTime={dashboard.server_time}
                    className="ring-0"
                  />
                </div>
                <p className="mt-1.5 text-xl font-semibold tracking-[-0.03em]">
                  {formatMoney(critical.amount, critical.currency)}
                  <span className="ml-2 text-sm font-normal text-ink-300">
                    {critical.customer_name ?? critical.paystack_dispute_id}
                  </span>
                </p>
              </div>
            </div>
            <Link href={`/disputes/${critical.id}`}>
              <Button className="w-full bg-white text-ink-950 hover:bg-ink-100 sm:w-auto">
                Review evidence <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </div>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Open disputes"
          value={stats?.open ?? metrics.disputes?.open ?? 0}
          icon={<ShieldAlert className="h-4 w-4" />}
          tone={metrics.disputes?.critical ? 'danger' : 'default'}
          detail={
            metrics.disputes?.critical
              ? `${metrics.disputes.critical} inside the 4-hour window`
              : 'No disputes inside the critical window'
          }
        />
        <StatCard
          label="Dispute win rate"
          value={percent(stats?.win_rate, 0)}
          icon={<TrendingUp className="h-4 w-4" />}
          tone="brand"
          detail={`${stats?.won ?? 0} won · ${stats?.lost ?? 0} lost`}
        />
        <StatCard
          label="Reconciliation rate"
          value={percent(metrics.reconciliation?.matched_pct, 0)}
          icon={<ListChecks className="h-4 w-4" />}
          detail={`${reconciliation?.needs_review ?? 0} payments need review`}
          delta={metrics.reconciliation?.delta_pct}
        />
        <StatCard
          label="Evidence readiness"
          value={metrics.readiness?.score ?? '—'}
          icon={<ShieldCheck className="h-4 w-4" />}
          tone={metrics.readiness?.label === 'vulnerable' ? 'amber' : 'default'}
          detail={
            metrics.readiness?.label
              ? titleCase(metrics.readiness.label)
              : 'Match payments to orders to score readiness'
          }
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.45fr_1fr]">
        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Reconciliation quick view"
              description="Payments synced and matched since the start of today."
              action={
                <Link href="/reconciliation">
                  <Button variant="outline" size="sm">
                    Open workspace <ArrowRight className="h-3.5 w-3.5" />
                  </Button>
                </Link>
              }
            />
            <CardBody className="grid gap-4 sm:grid-cols-3">
              <div className="rounded-xl bg-ink-50 px-4 py-3.5">
                <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500">
                  Synced today
                </p>
                <p className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-ink-950">
                  {reconciliation?.synced_today ?? 0}
                </p>
                <p className="mt-0.5 text-[11px] text-ink-400">Paystack transactions</p>
              </div>
              <div className="rounded-xl bg-brand-50 px-4 py-3.5">
                <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-brand-700">
                  Matched today
                </p>
                <p className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-brand-900">
                  {reconciliation?.matched_today ?? 0}
                </p>
                <p className="mt-0.5 text-[11px] text-brand-600">Linked to orders</p>
              </div>
              <div
                className={cn(
                  'rounded-xl px-4 py-3.5',
                  reconciliation?.needs_review ? 'bg-amber-50' : 'bg-ink-50',
                )}
              >
                <p
                  className={cn(
                    'text-[11px] font-semibold uppercase tracking-[0.08em]',
                    reconciliation?.needs_review ? 'text-amber-700' : 'text-ink-500',
                  )}
                >
                  Needs review
                </p>
                <p
                  className={cn(
                    'mt-1 text-2xl font-semibold tracking-[-0.03em]',
                    reconciliation?.needs_review ? 'text-amber-900' : 'text-ink-950',
                  )}
                >
                  {reconciliation?.needs_review ?? 0}
                </p>
                <p
                  className={cn(
                    'mt-0.5 text-[11px]',
                    reconciliation?.needs_review ? 'text-amber-600' : 'text-ink-400',
                  )}
                >
                  {reconciliation?.last_completed_at
                    ? `Last completed ${timeAgo(reconciliation.last_completed_at)}`
                    : 'No completed session yet'}
                </p>
              </div>
            </CardBody>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader title="Dispute activity" description="Opened vs won over 30 days" />
              <CardBody className="pt-2">
                <DisputeChart data={timelineQuery.data} />
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Match rate" description="Daily reconciliation health" />
              <CardBody className="pt-2">
                <ReconciliationChart data={healthQuery.data} />
              </CardBody>
            </Card>
          </div>

          <Card>
            <CardHeader
              title="Recent disputes"
              description="Sorted by the newest first; deadlines are live."
              action={
                <Link href="/disputes">
                  <Button variant="ghost" size="sm">
                    View all <ArrowRight className="h-3.5 w-3.5" />
                  </Button>
                </Link>
              }
            />
            {dashboard.recent_disputes?.length ? (
              <div className="divide-y divide-line">
                {dashboard.recent_disputes.slice(0, 4).map((dispute) => (
                  <Link
                    key={dispute.id}
                    href={`/disputes/${dispute.id}`}
                    className="flex flex-col gap-3 px-5 py-4 transition hover:bg-ink-50/60 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex min-w-0 items-start gap-3">
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-red-50 text-red-600">
                        <Gavel className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-[13px] font-semibold text-ink-900">
                            {formatMoney(dispute.amount, dispute.currency)}
                          </p>
                          <Badge tone={statusTone(dispute.status)}>
                            {STATUS_LABELS[dispute.status]}
                          </Badge>
                          {dispute.category ? (
                            <span className="text-[11px] text-ink-400">
                              {CATEGORY_LABELS[dispute.category]}
                            </span>
                          ) : null}
                        </div>
                        <p className="mt-1 truncate text-[12px] text-ink-500">
                          {dispute.customer?.name ?? dispute.customer?.email ?? 'Customer'} ·{' '}
                          {dispute.transaction_reference}
                        </p>
                      </div>
                    </div>
                    <Countdown dueAt={dispute.due_at} serverTime={dashboard.server_time} />
                  </Link>
                ))}
              </div>
            ) : (
              <div className="p-5">
                <EmptyState
                  icon={<ShieldCheck className="h-5 w-5" />}
                  title="No disputes yet"
                  description="When a chargeback arrives, it will appear here with its evidence readiness."
                />
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card className="overflow-hidden">
            <div className="bg-ink-950 px-5 py-5 text-white">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 text-brand-300" />
                  <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-300">
                    TrustLayer
                  </p>
                </div>
                <span
                  className={cn(
                    'rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide ring-1 ring-inset',
                    dashboard.trust
                      ? TRUST_TONE[dashboard.trust.state]
                      : 'bg-white/10 text-ink-200 ring-white/10',
                  )}
                >
                  {dashboard.trust ? TRUST_LABELS[dashboard.trust.state] : 'Not computed'}
                </span>
              </div>
              <p className="mt-4 text-2xl font-semibold tracking-[-0.03em]">
                {dashboard.trust?.label ?? 'Build your public proof'}
              </p>
              <p className="mt-1.5 text-[12px] leading-5 text-ink-300">
                {dashboard.trust?.updated_at
                  ? `Last updated ${timeAgo(dashboard.trust.updated_at)}`
                  : 'Complete reconciliation and fulfillment to unlock your trust profile.'}
              </p>
            </div>
            <CardBody className="space-y-3">
              <Link
                href="/trust"
                className="flex items-center justify-between rounded-xl border border-line px-3.5 py-3 text-[13px] font-semibold text-ink-700 transition hover:bg-ink-50"
              >
                View trust profile <ArrowRight className="h-4 w-4" />
              </Link>
              {dashboard.trust?.state === 'verified' ? (
                <p className="text-[12px] leading-5 text-ink-500">
                  Your public verification page is ready to share with customers.
                </p>
              ) : (
                <p className="text-[12px] leading-5 text-ink-500">
                  Six operational signals determine your state. TrustLayer explains exactly what to
                  improve next.
                </p>
              )}
            </CardBody>
          </Card>

          {dashboard.prompts?.length ? (
            <Card>
              <CardHeader
                title="Awaiting fulfillment"
                description="Paid orders without evidence. Capture it now."
              />
              <div className="divide-y divide-line">
                {dashboard.prompts.slice(0, 3).map((prompt) => (
                  <div key={prompt.order_id} className="flex items-center gap-3 px-5 py-3.5">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-50 text-amber-700">
                      <ShoppingBag className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-[12px] font-semibold text-ink-900">
                        Order {prompt.order_number ?? '—'}
                      </p>
                      <p className="text-[11px] text-ink-400">
                        {formatMoney(prompt.amount, prompt.currency)} paid
                      </p>
                    </div>
                    <Link href={`/fulfillments/new?order=${prompt.order_id}`}>
                      <Button size="sm" variant="secondary">
                        Log
                      </Button>
                    </Link>
                  </div>
                ))}
              </div>
            </Card>
          ) : null}

          <Card>
            <CardHeader title="Recent activity" description="The last events in your workspace" />
            {dashboard.activity?.length ? (
              <div className="space-y-1 p-3">
                {dashboard.activity.slice(0, 7).map((item, index) => {
                  const Icon = activityIcons[item.type] ?? Activity;
                  const href =
                    item.link.type === 'dispute' && item.link.id
                      ? `/disputes/${item.link.id}`
                      : item.link.type === 'order' && item.link.id
                        ? `/orders/${item.link.id}`
                        : item.link.type === 'reconciliation_session' && item.link.id
                          ? `/reconciliation/session/${item.link.id}`
                          : '/trust';
                  return (
                    <Link
                      key={`${item.type}-${item.occurred_at}-${index}`}
                      href={href}
                      className="flex items-start gap-3 rounded-xl px-2 py-2.5 transition hover:bg-ink-50"
                    >
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-ink-100 text-ink-500">
                        <Icon className="h-3.5 w-3.5" />
                      </div>
                      <div className="min-w-0">
                        <p className="text-[12px] font-medium leading-5 text-ink-700">
                          {item.title}
                        </p>
                        <p className="text-[10px] text-ink-400">{timeAgo(item.occurred_at)}</p>
                      </div>
                    </Link>
                  );
                })}
              </div>
            ) : (
              <div className="px-5 py-8 text-center text-[13px] text-ink-400">No activity yet</div>
            )}
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader
          title="Recent payments"
          description={`Activity for ${formatDate(dashboard.period.date_from)} – ${formatDate(dashboard.period.date_to)}`}
          action={
            <Link href="/reconciliation">
              <Button variant="outline" size="sm">
                All payments
              </Button>
            </Link>
          }
        />
        {dashboard.recent_transactions?.length ? (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Payment</th>
                  <th>Customer</th>
                  <th>Amount</th>
                  <th>Order</th>
                  <th>Reconciliation</th>
                  <th>Paid</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.recent_transactions.slice(0, 6).map((transaction) => (
                  <tr key={transaction.id}>
                    <td>
                      <p className="font-mono text-[12px] font-semibold text-ink-900">
                        {transaction.reference}
                      </p>
                      <p className="mt-0.5 text-[11px] capitalize text-ink-400">
                        {transaction.channel.replace(/_/g, ' ')}
                      </p>
                    </td>
                    <td>
                      <div className="flex items-center gap-2.5">
                        <Avatar
                          name={transaction.customer_name ?? transaction.customer_email}
                          size="sm"
                        />
                        <div>
                          <p className="text-[12px] font-medium text-ink-800">
                            {transaction.customer_name ?? 'Unknown'}
                          </p>
                          <p className="text-[11px] text-ink-400">
                            {transaction.customer_email ?? '—'}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="font-semibold text-ink-900">
                      {formatMoney(transaction.amount, transaction.currency)}
                    </td>
                    <td>{transaction.order?.order_number ?? '—'}</td>
                    <td>
                      <Badge
                        tone={
                          transaction.reconciliation_status === 'unmatched'
                            ? 'warning'
                            : transaction.reconciliation_status === 'flagged'
                              ? 'danger'
                              : 'success'
                        }
                      >
                        {RECONCILIATION_LABELS[transaction.reconciliation_status]}
                      </Badge>
                    </td>
                    <td className="text-[12px] text-ink-500">
                      {transaction.paid_at ? timeAgo(transaction.paid_at) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-5">
            <EmptyState
              icon={<CircleDollarSign className="h-5 w-5" />}
              title="No payments synced yet"
              description="Connect Paystack and sync transactions to start reconciling."
              action={
                <Link href="/settings#paystack">
                  <Button variant="outline">Connect Paystack</Button>
                </Link>
              }
            />
          </div>
        )}
      </Card>

      <div className="grid gap-4 sm:grid-cols-3">
        {[
          {
            label: 'Transactions',
            value: metrics.transactions?.successful ?? 0,
            icon: CircleDollarSign,
          },
          { label: 'Customers', value: null, icon: Users },
          { label: 'Orders', value: null, icon: ShoppingBag },
        ].map((item) => (
          <div
            key={item.label}
            className="flex items-center gap-3 rounded-2xl border border-line bg-white/60 px-4 py-3"
          >
            <item.icon className="h-4 w-4 text-ink-400" />
            <p className="text-[12px] text-ink-500">
              {item.value !== null ? `${item.value} successful ` : ''}
              {item.label.toLowerCase()} in this period
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
