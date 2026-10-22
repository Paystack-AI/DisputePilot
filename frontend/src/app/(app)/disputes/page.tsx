'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Gavel, RefreshCw, ShieldAlert, ShieldCheck, TrendingUp } from 'lucide-react';
import { toast } from 'sonner';
import { apiList, apiRequest, errorMessage } from '@/lib/api';
import { formatMoney, percent, timeAgo } from '@/lib/format';
import type { DisputeStats, DisputeSummary, PageMeta } from '@/lib/types';
import { CATEGORY_LABELS, STATUS_LABELS } from '@/lib/constants';
import { PageHeader } from '@/components/ui/page-header';
import { StatCard } from '@/components/ui/stat-card';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge, statusTone } from '@/components/ui/badge';
import { Countdown } from '@/components/ui/countdown';
import { EmptyState } from '@/components/ui/empty-state';
import { PageSkeleton } from '@/components/ui/skeleton';
import { Pagination } from '@/components/ui/pagination';
import { Tabs } from '@/components/ui/tabs';

const filters = [
  { value: 'all', label: 'All', status: undefined },
  { value: 'pending', label: 'Pending', status: 'pending,evidence_generated' },
  { value: 'submitted', label: 'Submitted', status: 'submitted' },
  { value: 'resolved', label: 'Resolved', status: 'won,lost,auto_accepted' },
];

export default function DisputesPage() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState(1);
  const activeFilter = filters.find((item) => item.value === filter) ?? filters[0];

  const disputesQuery = useQuery({
    queryKey: ['disputes', 'list', activeFilter.status, page],
    queryFn: () =>
      apiList<DisputeSummary>(
        `/disputes?sort=due_at&limit=12&page=${page}${activeFilter.status ? `&status=${activeFilter.status}` : ''}`,
      ),
    refetchInterval: 60_000,
  });
  const statsQuery = useQuery({
    queryKey: ['disputes', 'stats'],
    queryFn: () => apiRequest<DisputeStats>('/disputes/stats'),
  });

  const syncMutation = useMutation({
    mutationFn: () => apiRequest('/disputes/sync', { method: 'POST' }),
    onSuccess: () => {
      toast.success('Dispute sync queued');
      queryClient.invalidateQueries({ queryKey: ['disputes'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (disputesQuery.isLoading) return <PageSkeleton />;

  const stats = statsQuery.data;
  const meta: PageMeta | undefined = disputesQuery.data?.meta;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Defence"
        title="Disputes"
        description="Every deadline, evidence draft and outcome in one urgent-first queue."
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => syncMutation.mutate()}
              loading={syncMutation.isPending}
            >
              <RefreshCw className="h-4 w-4" /> Sync Paystack
            </Button>
            <Link href="/fulfillments/new">
              <Button variant="secondary">
                <ShieldCheck className="h-4 w-4" /> Add evidence
              </Button>
            </Link>
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Open disputes"
          value={stats?.open ?? 0}
          icon={<ShieldAlert className="h-4 w-4" />}
          tone={stats?.open ? 'danger' : 'default'}
          detail="Awaiting your response"
        />
        <StatCard
          label="Submitted"
          value={stats?.submitted ?? 0}
          icon={<Gavel className="h-4 w-4" />}
          detail="With Paystack for review"
        />
        <StatCard
          label="Win rate"
          value={percent(stats?.win_rate, 0)}
          icon={<TrendingUp className="h-4 w-4" />}
          tone="brand"
          detail={`${stats?.won ?? 0} won · ${stats?.lost ?? 0} lost`}
        />
        <StatCard
          label="Avg response"
          value={stats?.avg_response_hours ? `${stats.avg_response_hours.toFixed(1)}h` : '—'}
          icon={<ShieldCheck className="h-4 w-4" />}
          detail="Opening to merchant response"
        />
      </div>

      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
        <Tabs
          items={filters.map((item) => ({ value: item.value, label: item.label }))}
          value={filter}
          onChange={(value) => {
            setFilter(value);
            setPage(1);
          }}
        />
        <p className="text-[12px] text-ink-500">
          {meta?.total ?? 0} dispute{(meta?.total ?? 0) === 1 ? '' : 's'}
        </p>
      </div>

      {disputesQuery.data?.data.length ? (
        <>
          <div className="grid gap-4 xl:grid-cols-2">
            {disputesQuery.data.data.map((dispute) => (
              <Link key={dispute.id} href={`/disputes/${dispute.id}`} className="group">
                <Card className="h-full p-5 transition group-hover:-translate-y-0.5 group-hover:border-brand-200 group-hover:shadow-float">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex min-w-0 items-start gap-3">
                      <div
                        className={
                          dispute.urgency === 'critical'
                            ? 'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-50 text-red-600 ring-1 ring-inset ring-red-200'
                            : 'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ink-100 text-ink-500'
                        }
                      >
                        <Gavel className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-lg font-semibold tracking-[-0.03em] text-ink-950">
                            {formatMoney(dispute.amount, dispute.currency)}
                          </p>
                          <Badge tone={statusTone(dispute.status)}>
                            {STATUS_LABELS[dispute.status]}
                          </Badge>
                        </div>
                        <p className="mt-1 text-[12px] font-medium text-ink-600">
                          {dispute.category
                            ? CATEGORY_LABELS[dispute.category]
                            : 'Awaiting classification'}
                        </p>
                      </div>
                    </div>
                    <Countdown dueAt={dispute.due_at} serverTime={meta?.server_time} />
                  </div>

                  <div className="mt-4 rounded-xl bg-ink-50 px-3.5 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-[12px] font-semibold text-ink-800">
                          {dispute.customer?.name ?? dispute.customer?.email ?? 'Unknown customer'}
                        </p>
                        <p className="mt-0.5 truncate font-mono text-[11px] text-ink-400">
                          {dispute.transaction_reference}
                        </p>
                      </div>
                      <ArrowRight className="h-4 w-4 shrink-0 text-ink-400 transition group-hover:translate-x-0.5 group-hover:text-brand-600" />
                    </div>
                  </div>

                  <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-ink-400">
                    <span className="rounded-md bg-white px-2 py-1 ring-1 ring-inset ring-line">
                      Opened {timeAgo(dispute.created_at)}
                    </span>
                    {dispute.readiness ? (
                      <span
                        className={
                          dispute.readiness.label === 'well_defended'
                            ? 'rounded-md bg-brand-50 px-2 py-1 font-semibold text-brand-700'
                            : dispute.readiness.label === 'vulnerable'
                              ? 'rounded-md bg-red-50 px-2 py-1 font-semibold text-red-700'
                              : 'rounded-md bg-amber-50 px-2 py-1 font-semibold text-amber-700'
                        }
                      >
                        Readiness {dispute.readiness.score}
                      </span>
                    ) : null}
                    {dispute.quality ? (
                      <span className="rounded-md bg-white px-2 py-1 font-semibold text-ink-600 ring-1 ring-inset ring-line">
                        Draft {dispute.quality.score}
                      </span>
                    ) : null}
                  </div>
                </Card>
              </Link>
            ))}
          </div>
          <div className="table-shell">
            <Pagination meta={meta} onPageChange={setPage} />
          </div>
        </>
      ) : (
        <EmptyState
          icon={<ShieldCheck className="h-5 w-5" />}
          title={filter === 'all' ? 'No disputes yet' : 'Nothing in this view'}
          description={
            filter === 'all'
              ? 'When Paystack sends a dispute, it appears here with a live countdown and readiness score.'
              : 'Try another filter or sync Paystack for the latest disputes.'
          }
          action={
            filter === 'all' ? (
              <Link href="/reconciliation">
                <Button variant="outline">Review reconciliation</Button>
              </Link>
            ) : null
          }
        />
      )}
    </div>
  );
}
