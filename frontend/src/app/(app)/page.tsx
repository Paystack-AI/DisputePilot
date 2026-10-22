'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { format, subDays } from 'date-fns';
import {
  AlertTriangle,
  ArrowLeftRight,
  ArrowRight,
  BadgeCheck,
  Camera,
  CheckCircle2,
  ChevronRight,
  FileWarning,
  Gavel,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  CircleCheck,
} from 'lucide-react';
import { apiRequest } from '@/lib/api';
import { cn } from '@/lib/cn';
import {
  channelLabel,
  formatDateTime,
  formatMoney,
  formatTime,
  percent,
  timeAgo,
} from '@/lib/format';
import type {
  Dashboard,
  DisputeSummary,
  DisputeTimeline,
  Merchant,
  ReconciliationHealth,
  Transaction,
} from '@/lib/types';
import { CATEGORY_LABELS, STATUS_LABELS, TRANSACTION_LABELS, TRUST_LABELS } from '@/lib/constants';
import { activityHref, href } from '@/lib/links';
import { StatCard } from '@/components/ui/stat-card';
import { Card } from '@/components/ui/card';
import { Badge, statusTone } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Countdown, clockLabel, useRemaining } from '@/components/ui/countdown';
import { PageSkeleton } from '@/components/ui/skeleton';
import { EmptyState } from '@/components/ui/empty-state';
import { Select } from '@/components/ui/input';
import { DisputeChart } from '@/components/dashboard/dispute-chart';
import { ReconciliationChart } from '@/components/dashboard/reconciliation-chart';

const PERIODS = [7, 30, 90] as const;

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

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

export default function DashboardPage() {
  const [days, setDays] = useState<(typeof PERIODS)[number]>(7);
  const [chart, setChart] = useState<'disputes' | 'reconciliation'>('disputes');

  const today = new Date();
  const dateFrom = format(subDays(today, days - 1), 'yyyy-MM-dd');
  const dateTo = format(today, 'yyyy-MM-dd');

  const merchantQuery = useQuery({
    queryKey: ['merchant', 'me'],
    queryFn: () => apiRequest<Merchant>('/auth/me'),
    staleTime: 5 * 60_000,
  });
  const dashboardQuery = useQuery({
    queryKey: ['dashboard', days],
    queryFn: () => apiRequest<Dashboard>(`/dashboard?date_from=${dateFrom}&date_to=${dateTo}`),
    refetchInterval: 60_000,
  });
  const chartDays = days === 90 ? 90 : 30;
  const timelineQuery = useQuery({
    queryKey: ['dashboard', 'dispute-timeline', chartDays],
    queryFn: () => apiRequest<DisputeTimeline>(`/dashboard/dispute-timeline?days=${chartDays}`),
  });
  const healthQuery = useQuery({
    queryKey: ['dashboard', 'reconciliation-health', chartDays],
    queryFn: () =>
      apiRequest<ReconciliationHealth>(`/dashboard/reconciliation-health?days=${chartDays}`),
    enabled: chart === 'reconciliation',
  });

  if (dashboardQuery.isLoading) return <PageSkeleton />;
  if (dashboardQuery.isError || !dashboardQuery.data) {
    return (
      <EmptyState
        icon={<RefreshCw className="h-5 w-5" />}
        title="We couldn't load your dashboard"
        description={
          dashboardQuery.error instanceof Error ? dashboardQuery.error.message : 'Try again.'
        }
        action={<Button onClick={() => dashboardQuery.refetch()}>Try again</Button>}
      />
    );
  }

  const d = dashboardQuery.data;
  const m = d.metrics;
  const business = merchantQuery.data?.business_name;

  return (
    <div className="space-y-5">
      {d.critical_dispute ? (
        <CriticalBanner dispute={d.critical_dispute} serverTime={d.server_time} />
      ) : null}

      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
        <div>
          <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-ink-950">
            {greeting()}
            {business ? `, ${business}` : ''}
          </h1>
          <p className="mt-0.5 text-[13px] text-ink-500">
            Here&apos;s what&apos;s happening with your business.
          </p>
        </div>
        <Select
          value={days}
          onChange={(event) => setDays(Number(event.target.value) as typeof days)}
          className="h-9 w-auto py-1.5 text-[13px]"
          aria-label="Period"
        >
          {PERIODS.map((value) => (
            <option key={value} value={value}>
              Last {value} days
            </option>
          ))}
        </Select>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        <StatCard
          label="Transactions"
          value={m.transactions ? m.transactions.count.toLocaleString() : '—'}
          delta={m.transactions?.delta_pct}
          detail={
            m.transactions ? `${m.transactions.successful.toLocaleString()} successful` : undefined
          }
          icon={<ArrowLeftRight />}
          tone="brand"
          href="/transactions"
        />
        <StatCard
          label="Open disputes"
          value={m.disputes?.open ?? '—'}
          detail={
            m.disputes?.critical ? (
              <span className="text-red-600">{m.disputes.critical} critical</span>
            ) : (
              'None critical'
            )
          }
          icon={<ShieldAlert />}
          tone={m.disputes?.critical ? 'danger' : 'default'}
          href="/disputes?status=pending"
        />
        <StatCard
          label="Dispute readiness"
          value={m.readiness?.score !== null && m.readiness ? `${m.readiness.score}%` : '—'}
          detail={
            m.readiness?.distribution?.vulnerable ? (
              <span className="text-amber-600">
                {m.readiness.distribution.vulnerable}% vulnerable
              </span>
            ) : (
              'Of matched payments'
            )
          }
          icon={<ShieldCheck />}
          tone="success"
          href="/transactions?reconciliation_status=auto_matched"
        />
        <StatCard
          label="Payments matched"
          value={percent(m.reconciliation?.matched_pct)}
          delta={m.reconciliation?.delta_pct}
          detail={
            m.reconciliation?.unmatched ? `${m.reconciliation.unmatched} unmatched` : 'All matched'
          }
          icon={<CircleCheck />}
          tone="amber"
          href="/reconciliation"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.75fr_1fr]">
        <Card>
          <div className="flex items-center justify-between gap-3 px-5 pt-4">
            <h2 className="text-[14px] font-semibold text-ink-900">
              {chart === 'disputes' ? 'Dispute activity' : 'Match rate'}
            </h2>
            <div className="flex rounded-md bg-ink-100 p-0.5 text-[12px]">
              {(['disputes', 'reconciliation'] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setChart(value)}
                  className={cn(
                    'rounded px-2.5 py-1 font-medium transition',
                    chart === value ? 'bg-brand-600 text-white' : 'text-ink-600 hover:text-ink-900',
                  )}
                >
                  {value === 'disputes' ? 'Disputes' : 'Reconciliation'}
                </button>
              ))}
            </div>
          </div>
          <div className="px-3 pb-3 pt-2">
            {chart === 'disputes' ? (
              <DisputeChart data={timelineQuery.data} />
            ) : (
              <ReconciliationChart data={healthQuery.data} />
            )}
          </div>
        </Card>

        <TrustCard trust={d.trust} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="flex flex-col p-5">
          <h2 className="text-[14px] font-semibold text-ink-900">Reconciliation</h2>
          {d.reconciliation ? (
            <>
              <p className="mt-1.5 text-[12px] text-ink-500">
                {d.reconciliation.synced_today} synced today · {d.reconciliation.matched_today}{' '}
                matched ·{' '}
                <Link href="/reconciliation" className="link">
                  {d.reconciliation.needs_review} need review
                </Link>
              </p>
              <div className="mt-4">
                <Link href="/reconciliation">
                  <Button size="sm">Start reconciliation</Button>
                </Link>
              </div>
              <p className="mt-auto pt-4 text-[11px] text-ink-400">
                {d.reconciliation.last_completed_at
                  ? `Last completed ${timeAgo(d.reconciliation.last_completed_at)}`
                  : 'No session completed yet'}
              </p>
            </>
          ) : (
            <p className="mt-2 text-[12px] text-ink-400">Unavailable right now.</p>
          )}
        </Card>

        <Card className="p-5">
          <h2 className="text-[14px] font-semibold text-ink-900">Dispute readiness</h2>
          {m.readiness && m.readiness.score !== null ? (
            <div className="mt-3 flex items-center gap-4">
              <ScoreRing score={m.readiness.score} />
              <ul className="space-y-1 text-[12px]">
                <li className="text-emerald-600">
                  {m.readiness.distribution.well_defended ?? 0}% well-defended
                </li>
                <li className="text-amber-600">
                  {m.readiness.distribution.moderate ?? 0}% moderate
                </li>
                <li>
                  <Link
                    href="/transactions?reconciliation_status=auto_matched"
                    className="inline-flex items-center gap-0.5 text-red-600 hover:underline"
                  >
                    {m.readiness.distribution.vulnerable ?? 0}% vulnerable
                    <ChevronRight className="h-3 w-3" />
                  </Link>
                </li>
              </ul>
            </div>
          ) : (
            <p className="mt-2 text-[12px] leading-5 text-ink-500">
              Scored once payments are matched to orders.
            </p>
          )}
        </Card>

        <Card className="p-5">
          <h2 className="text-[14px] font-semibold text-ink-900">Needs your attention</h2>
          {d.prompts?.length ? (
            <ul className="mt-2 divide-y divide-line">
              {d.prompts.slice(0, 3).map((prompt) => (
                <li key={prompt.order_id} className="py-2.5 first:pt-1">
                  <p className="text-[12px] leading-5 text-ink-600">
                    <Link href={href.order(prompt.order_id)} className="link">
                      Order {prompt.order_number ?? 'without number'}
                    </Link>{' '}
                    was paid {formatMoney(prompt.amount, prompt.currency)}. Has it been fulfilled?
                  </p>
                  <Link href={href.logFulfillment(prompt.order_id)}>
                    <Button
                      size="sm"
                      className="mt-2 bg-emerald-600 text-white hover:brightness-95 dark:bg-emerald-500"
                    >
                      <Camera className="h-3.5 w-3.5" /> Log fulfillment
                    </Button>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-[12px] text-ink-500">You&apos;re all caught up.</p>
          )}
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.4fr_1fr]">
        <RecentTransactions rows={d.recent_transactions} />
        <RecentDisputes rows={d.recent_disputes} serverTime={d.server_time} />
      </div>

      {d.activity?.length ? (
        <Card>
          <div className="px-5 pt-4">
            <h2 className="text-[14px] font-semibold text-ink-900">Activity</h2>
          </div>
          <ul className="divide-y divide-line px-5 pb-2 pt-2">
            {d.activity.slice(0, 8).map((item) => {
              const Icon = activityIcons[item.type];
              const target = activityHref(item);
              const body = (
                <>
                  <Icon className="h-4 w-4 shrink-0 text-ink-400" />
                  <span className="min-w-0 flex-1 truncate text-[13px] text-ink-700">
                    {item.title}
                  </span>
                  <span className="shrink-0 text-[11px] text-ink-400">
                    {timeAgo(item.occurred_at)}
                  </span>
                </>
              );
              return (
                <li key={`${item.type}-${item.occurred_at}`}>
                  {target ? (
                    <Link
                      href={target}
                      className="-mx-2 flex items-center gap-3 rounded-md px-2 py-2.5 hover:bg-ink-50"
                    >
                      {body}
                    </Link>
                  ) : (
                    <div className="flex items-center gap-3 py-2.5">{body}</div>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

function CriticalBanner({
  dispute,
  serverTime,
}: {
  dispute: NonNullable<Dashboard['critical_dispute']>;
  serverTime: string;
}) {
  const remaining = useRemaining(dispute.due_at, serverTime);
  return (
    <div className="flex flex-col gap-3 rounded-lg bg-red-600 px-4 py-3 text-white dark:bg-red-500/90 sm:flex-row sm:items-center">
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 text-[13px] font-medium">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        <span className="uppercase tracking-[0.04em]">Dispute requires attention</span>
        <span className="text-white/70">·</span>
        <span>{formatMoney(dispute.amount, dispute.currency)}</span>
        {dispute.customer_name ? (
          <>
            <span className="text-white/70">·</span>
            <span>{dispute.customer_name}</span>
          </>
        ) : null}
        <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold tabular-nums text-red-600">
          {clockLabel(remaining)} remaining
        </span>
      </div>
      <Link
        href={href.dispute(dispute.id)}
        className="inline-flex items-center gap-1 self-start rounded-md bg-white px-3 py-1.5 text-[12px] font-semibold text-red-600 hover:bg-red-50 sm:self-auto"
      >
        Review now <ArrowRight className="h-3.5 w-3.5" />
      </Link>
    </div>
  );
}

function TrustCard({ trust }: { trust: Dashboard['trust'] }) {
  const verified = trust?.state === 'verified';
  return (
    <Card className="flex flex-col p-5">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-[14px] font-semibold text-ink-900">TrustLayer status</h2>
        {trust ? (
          <Badge tone={statusTone(trust.state)} dot>
            {TRUST_LABELS[trust.state]}
          </Badge>
        ) : null}
      </div>
      {trust ? (
        <>
          <div className="mt-4 flex items-start gap-3">
            <ShieldCheck
              className={cn('h-8 w-8 shrink-0', verified ? 'text-emerald-600' : 'text-ink-400')}
            />
            <div>
              <p className="text-[13px] font-semibold text-ink-900">{trust.label}</p>
              <p className="text-[11px] text-ink-500">
                {trust.updated_at
                  ? `Updated ${formatDateTime(trust.updated_at)}`
                  : 'Not computed yet'}
              </p>
            </div>
          </div>
          <ul className="mt-4 space-y-2 text-[12px] text-ink-600">
            {[
              'Payment history',
              'Fulfillment activity',
              'Dispute handling',
              'Operational consistency',
            ].map((signal) => (
              <li key={signal} className="flex items-center gap-2">
                <CheckCircle2 className="h-3.5 w-3.5 text-ink-300" /> {signal}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="mt-3 text-[12px] text-ink-500">
          Your trust profile is created the first time you open TrustLayer.
        </p>
      )}
      <Link
        href="/trust"
        className="mt-auto inline-flex items-center gap-1 pt-4 text-[12px] font-medium text-brand-600 hover:underline"
      >
        See what could improve it <ChevronRight className="h-3.5 w-3.5" />
      </Link>
    </Card>
  );
}

function ScoreRing({ score }: { score: number }) {
  const radius = 30;
  const circumference = 2 * Math.PI * radius;
  const tone = score >= 70 ? 'text-emerald-500' : score >= 40 ? 'text-amber-500' : 'text-red-500';
  return (
    <div className="relative h-20 w-20 shrink-0">
      <svg viewBox="0 0 72 72" className="h-20 w-20 -rotate-90">
        <circle cx="36" cy="36" r={radius} fill="none" strokeWidth="7" className="stroke-ink-100" />
        <circle
          cx="36"
          cy="36"
          r={radius}
          fill="none"
          strokeWidth="7"
          strokeLinecap="round"
          stroke="currentColor"
          className={tone}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - score / 100)}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-[17px] font-semibold text-ink-950">
        {score}%
      </span>
    </div>
  );
}

function RecentTransactions({ rows }: { rows: Transaction[] | null }) {
  const router = useRouter();
  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-between px-5 pb-2 pt-4">
        <h2 className="text-[14px] font-semibold text-ink-900">Recent transactions</h2>
        <Link href="/transactions" className="link text-[12px]">
          View all
        </Link>
      </div>
      {rows?.length ? (
        <div className="overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th>Reference</th>
                <th>Customer</th>
                <th>Amount</th>
                <th>Channel</th>
                <th>Status</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr
                  key={t.id}
                  className="row-link"
                  onClick={() => router.push(href.transaction(t.reference))}
                >
                  <td>
                    <Link
                      href={href.transaction(t.reference)}
                      className="font-mono text-[12px] text-ink-900 hover:text-brand-600"
                      onClick={(event) => event.stopPropagation()}
                    >
                      {t.reference}
                    </Link>
                  </td>
                  <td className="whitespace-nowrap text-[13px]">
                    {t.customer ? (
                      <Link
                        href={href.customer(t.customer.id)}
                        className="text-ink-800 hover:text-brand-600 hover:underline"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {t.customer.name ?? t.customer.email ?? t.customer_name ?? 'Customer'}
                      </Link>
                    ) : (
                      (t.customer_name ?? t.customer_email ?? '—')
                    )}
                  </td>
                  <td className="font-medium tabular-nums text-ink-900">
                    {formatMoney(t.amount, t.currency)}
                  </td>
                  <td className="whitespace-nowrap text-[12px]">{channelLabel(t.channel)}</td>
                  <td>
                    <Badge tone={statusTone(t.status)} dot>
                      {TRANSACTION_LABELS[t.status]}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap text-[12px] text-ink-500">
                    {t.paid_at ? `${timeAgo(t.paid_at)}, ${formatTime(t.paid_at)}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-5 pb-5 text-[12px] text-ink-500">No payments in this period.</p>
      )}
    </Card>
  );
}

function RecentDisputes({
  rows,
  serverTime,
}: {
  rows: DisputeSummary[] | null;
  serverTime: string;
}) {
  return (
    <Card>
      <div className="flex items-center justify-between px-5 pb-1 pt-4">
        <h2 className="text-[14px] font-semibold text-ink-900">Recent disputes</h2>
        <Link href="/disputes" className="link text-[12px]">
          View all
        </Link>
      </div>
      {rows?.length ? (
        <ul className="divide-y divide-line px-5 pb-2">
          {rows.map((dispute) => {
            const open = dispute.status === 'pending' || dispute.status === 'evidence_generated';
            return (
              <li key={dispute.id}>
                <Link
                  href={href.dispute(dispute.id)}
                  className="-mx-2 flex items-center gap-3 rounded-md px-2 py-3 hover:bg-ink-50"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium text-ink-900">
                      {dispute.reason ??
                        (dispute.category ? CATEGORY_LABELS[dispute.category] : 'Dispute')}
                    </p>
                    <p className="truncate text-[11px] text-ink-500">
                      {dispute.paystack_dispute_id} ·{' '}
                      {formatMoney(dispute.amount, dispute.currency)}
                      {dispute.customer?.name ? ` · ${dispute.customer.name}` : ''}
                    </p>
                  </div>
                  {open ? (
                    <Countdown dueAt={dispute.due_at} serverTime={serverTime} compact />
                  ) : (
                    <Badge tone={statusTone(dispute.status)} dot>
                      {STATUS_LABELS[dispute.status]}
                    </Badge>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="px-5 pb-5 text-[12px] text-ink-500">No disputes. Keep it that way.</p>
      )}
    </Card>
  );
}
