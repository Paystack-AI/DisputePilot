'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  Building2,
  CircleDollarSign,
  CreditCard,
  FileWarning,
  Loader2,
  ShieldCheck,
  ShoppingBag,
  Users,
} from 'lucide-react';
import { apiList, apiRequest, errorMessage } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDate, formatNumber, timeAgo } from '@/lib/format';
import type { AdminMerchantListItem, AdminOverview } from '@/lib/types';
import { TRUST_LABELS, TRUST_TONE } from '@/lib/constants';
import { PageHeader } from '@/components/ui/page-header';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';

const TRUST_ORDER = ['verified', 'building', 'new', 'review'] as const;

export default function AdminOverviewPage() {
  const overviewQuery = useQuery({
    queryKey: ['admin', 'overview'],
    queryFn: () => apiRequest<AdminOverview>('/admin/overview', { admin: true }),
  });
  const merchantsQuery = useQuery({
    queryKey: ['admin', 'merchants', 'recent'],
    queryFn: () =>
      apiList<AdminMerchantListItem>('/admin/merchants?page=1&limit=6', { admin: true }),
  });

  if (overviewQuery.isLoading) {
    return (
      <div className="flex h-72 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
      </div>
    );
  }

  if (overviewQuery.isError || !overviewQuery.data) {
    return (
      <div className="space-y-5">
        <PageHeader title="Overview" />
        <Alert tone="danger" title="Could not load installation overview">
          {errorMessage(overviewQuery.error)}
        </Alert>
      </div>
    );
  }

  const overview = overviewQuery.data;
  const merchants = merchantsQuery.data?.data ?? [];
  const trustTotal = Object.values(overview.trust_states).reduce((sum, value) => sum + value, 0);
  const successRate =
    overview.total_transactions > 0
      ? (overview.successful_transactions / overview.total_transactions) * 100
      : 0;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Operator console"
        title="Installation overview"
        description="A read-only snapshot of every merchant, payment and dispute on this deployment."
        actions={
          <Link
            href="/admin/merchants"
            className="inline-flex items-center gap-1.5 rounded-xl bg-ink-950 px-3.5 py-2.5 text-[12px] font-semibold text-white transition hover:bg-ink-800"
          >
            All merchants <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric
          label="Merchants"
          value={overview.total_merchants}
          detail={`${overview.active_merchants} active · ${overview.verified_merchants} verified`}
          icon={<Building2 className="h-4 w-4" />}
          tone="brand"
        />
        <Metric
          label="Paystack connected"
          value={overview.paystack_connected_merchants}
          detail={`${overview.onboarding_completed_merchants} onboarding complete`}
          icon={<CreditCard className="h-4 w-4" />}
          tone="ink"
        />
        <Metric
          label="Transactions"
          value={overview.total_transactions}
          detail={`${successRate.toFixed(1)}% successful`}
          icon={<CircleDollarSign className="h-4 w-4" />}
          tone="ink"
        />
        <Metric
          label="Disputes"
          value={overview.total_disputes}
          detail={`${overview.open_disputes} currently open`}
          icon={<FileWarning className="h-4 w-4" />}
          tone={overview.open_disputes > 0 ? 'amber' : 'ink'}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader
            title="Trust distribution"
            description="Where merchants sit across the four public states."
            action={<ShieldCheck className="h-4 w-4 text-brand-600" />}
          />
          <CardBody className="space-y-4">
            {TRUST_ORDER.map((state) => {
              const count = overview.trust_states[state] ?? 0;
              const share = trustTotal > 0 ? (count / trustTotal) * 100 : 0;
              return (
                <div key={state}>
                  <div className="flex items-center justify-between gap-3 text-[12px]">
                    <div className="flex items-center gap-2">
                      <span
                        className={cn(
                          'inline-flex rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide ring-1 ring-inset',
                          TRUST_TONE[state],
                        )}
                      >
                        {TRUST_LABELS[state]}
                      </span>
                      <span className="text-ink-400">{count} merchants</span>
                    </div>
                    <span className="font-semibold text-ink-800">{share.toFixed(0)}%</span>
                  </div>
                  <Progress
                    value={share}
                    tone={
                      state === 'review'
                        ? 'red'
                        : state === 'building'
                          ? 'amber'
                          : state === 'new'
                            ? 'ink'
                            : 'brand'
                    }
                    className="mt-1.5"
                  />
                </div>
              );
            })}
            {trustTotal === 0 ? (
              <p className="py-6 text-center text-[12px] text-ink-400">
                No trust profiles computed yet.
              </p>
            ) : null}
          </CardBody>
        </Card>

        <div className="grid grid-cols-2 gap-3">
          <SmallStat
            icon={<ShoppingBag className="h-4 w-4" />}
            label="Orders"
            value={overview.total_orders}
            href="/admin/merchants"
          />
          <SmallStat
            icon={<Users className="h-4 w-4" />}
            label="Customers"
            value={overview.total_customers}
            href="/admin/merchants"
          />
          <SmallStat
            icon={<BarChart3 className="h-4 w-4" />}
            label="Successful"
            value={overview.successful_transactions}
            detail={`${successRate.toFixed(0)}% of all payments`}
            href="/admin/merchants"
          />
          <SmallStat
            icon={<FileWarning className="h-4 w-4" />}
            label="Open disputes"
            value={overview.open_disputes}
            detail="Needs merchant action"
            href="/admin/merchants"
          />
        </div>
      </div>

      <Card>
        <CardHeader
          title="Newest merchants"
          description="Latest workspaces to join the installation."
          action={
            <Link
              href="/admin/merchants"
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-brand-700 hover:text-brand-800"
            >
              View all <ArrowUpRight className="h-3 w-3" />
            </Link>
          }
        />
        <CardBody className="px-0 py-0">
          {merchantsQuery.isLoading ? (
            <div className="flex h-32 items-center justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-brand-600" />
            </div>
          ) : merchants.length ? (
            <div className="divide-y divide-line">
              {merchants.map((merchant) => (
                <Link
                  key={merchant.id}
                  href={`/admin/merchants/${merchant.id}`}
                  className="flex items-center justify-between gap-3 px-5 py-3.5 transition hover:bg-ink-50/60"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-[11px] font-bold text-brand-700">
                      {merchant.business_name.slice(0, 2).toUpperCase()}
                    </div>
                    <div className="min-w-0">
                      <p className="truncate text-[12px] font-semibold text-ink-900">
                        {merchant.business_name}
                      </p>
                      <p className="truncate text-[10px] text-ink-400">
                        {merchant.email ?? 'No email'} · joined {formatDate(merchant.created_at)}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <div className="hidden text-right sm:block">
                      <p className="text-[10px] text-ink-400">
                        {formatNumber(merchant.transaction_count)} tx · {merchant.dispute_count}{' '}
                        disputes
                      </p>
                      <p className="text-[9px] text-ink-400">{timeAgo(merchant.created_at)}</p>
                    </div>
                    {merchant.trust_state ? (
                      <span
                        className={cn(
                          'rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide ring-1 ring-inset',
                          TRUST_TONE[merchant.trust_state],
                        )}
                      >
                        {TRUST_LABELS[merchant.trust_state]}
                      </span>
                    ) : (
                      <Badge tone="neutral">No profile</Badge>
                    )}
                    <ArrowRight className="h-3.5 w-3.5 text-ink-300" />
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <p className="px-5 py-10 text-center text-[12px] text-ink-400">No merchants yet.</p>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
  icon,
  tone,
}: {
  label: string;
  value: number;
  detail: string;
  icon: React.ReactNode;
  tone: 'brand' | 'ink' | 'amber';
}) {
  return (
    <div className="rounded-2xl border border-line bg-white p-4">
      <div
        className={cn(
          'flex h-9 w-9 items-center justify-center rounded-xl',
          tone === 'brand'
            ? 'bg-brand-50 text-brand-700'
            : tone === 'amber'
              ? 'bg-amber-50 text-amber-700'
              : 'bg-ink-50 text-ink-600',
        )}
      >
        {icon}
      </div>
      <p className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-ink-950">
        {formatNumber(value)}
      </p>
      <p className="mt-0.5 text-[11px] font-medium text-ink-600">{label}</p>
      <p className="mt-1 text-[10px] text-ink-400">{detail}</p>
    </div>
  );
}

function SmallStat({
  icon,
  label,
  value,
  detail,
  href,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  detail?: string;
  href: string;
}) {
  return (
    <Link
      href={href}
      className="group rounded-2xl border border-line bg-white p-4 transition hover:border-brand-200 hover:bg-brand-50/30"
    >
      <div className="flex items-center justify-between">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink-50 text-ink-500 group-hover:text-brand-700">
          {icon}
        </span>
        <ArrowUpRight className="h-3 w-3 text-ink-300 group-hover:text-brand-600" />
      </div>
      <p className="mt-3 text-lg font-semibold tracking-[-0.02em] text-ink-950">
        {formatNumber(value)}
      </p>
      <p className="text-[11px] font-medium text-ink-600">{label}</p>
      {detail ? <p className="mt-0.5 text-[10px] text-ink-400">{detail}</p> : null}
    </Link>
  );
}
