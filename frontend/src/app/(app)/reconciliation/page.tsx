'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  CalendarRange,
  CheckCircle2,
  History,
  Loader2,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import { toast } from 'sonner';
import { ApiError, apiList, apiRequest, errorMessage } from '@/lib/api';
import { formatDate, formatDateTime, timeAgo } from '@/lib/format';
import type {
  Order,
  ReconciliationSession,
  ReconciliationSummary,
  ReconciliationView,
  Transaction,
} from '@/lib/types';
import { PageHeader } from '@/components/ui/page-header';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input, Label } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { Alert } from '@/components/ui/alert';
import { PageSkeleton } from '@/components/ui/skeleton';
import { ReconciliationSessionView } from '@/components/reconciliation/session-view';

export default function ReconciliationPage() {
  const queryClient = useQueryClient();
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const currentQuery = useQuery({
    queryKey: ['reconciliation', 'current'],
    queryFn: () => apiRequest<ReconciliationView>('/reconciliation/current'),
    retry: false,
  });
  const summaryQuery = useQuery({
    queryKey: ['reconciliation', 'summary'],
    queryFn: () => apiRequest<ReconciliationSummary>('/reconciliation/summary'),
  });
  const sessionsQuery = useQuery({
    queryKey: ['reconciliation', 'sessions'],
    queryFn: () => apiList<ReconciliationSession>('/reconciliation/sessions?limit=8'),
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['reconciliation'] });
    queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    queryClient.invalidateQueries({ queryKey: ['orders'] });
  };

  const startMutation = useMutation({
    mutationFn: () =>
      apiRequest<ReconciliationView>('/reconciliation/start', {
        method: 'POST',
        body: startDate && endDate ? { date_range_start: startDate, date_range_end: endDate } : {},
      }),
    onSuccess: () => {
      toast.success('Reconciliation session ready');
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const completeMutation = useMutation({
    mutationFn: () =>
      apiRequest<ReconciliationSession>('/reconciliation/complete', { method: 'POST' }),
    onSuccess: () => {
      toast.success('Reconciliation completed');
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const decide = async (type: 'accept' | 'reject', transactionId: string, orderId: string) => {
    setBusyKey(`${type}-${transactionId}`);
    try {
      await apiRequest(`/reconciliation/${type}-match`, {
        method: 'POST',
        body: { transaction_id: transactionId, order_id: orderId },
      });
      toast.success(type === 'accept' ? 'Match accepted' : 'Suggestion dismissed');
      refresh();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setBusyKey(null);
    }
  };

  const linkOrder = async (transaction: Transaction, order: Order) => {
    setBusyKey(`link-${transaction.id}`);
    try {
      await apiRequest(`/transactions/${encodeURIComponent(transaction.reference)}/match`, {
        method: 'PUT',
        body: { order_id: order.id },
      });
      toast.success('Payment linked to order');
      refresh();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setBusyKey(null);
    }
  };

  const resolveOrder = async (orderId: string, resolution: 'cash_payment' | 'payment_failed') => {
    setBusyKey(`resolve-${orderId}`);
    try {
      await apiRequest(`/orders/${orderId}/resolve`, {
        method: 'PUT',
        body: { resolution },
      });
      toast.success(resolution === 'cash_payment' ? 'Order marked as cash' : 'Order marked failed');
      refresh();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setBusyKey(null);
    }
  };

  const unflagTransaction = async (reference: string) => {
    setBusyKey(`unflag-${reference}`);
    try {
      await apiRequest(`/transactions/${encodeURIComponent(reference)}/unflag`, { method: 'PUT' });
      toast.success('Flag dismissed');
      refresh();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setBusyKey(null);
    }
  };

  const unflagOrder = async (orderId: string) => {
    setBusyKey(`unflag-order-${orderId}`);
    try {
      await apiRequest(`/orders/${orderId}/unflag`, { method: 'PUT' });
      toast.success('Flag dismissed');
      refresh();
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setBusyKey(null);
    }
  };

  if (currentQuery.isLoading) return <PageSkeleton />;
  const noSession = currentQuery.error instanceof ApiError && currentQuery.error.status === 404;
  const view = currentQuery.data;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Daily workspace"
        title="Reconciliation"
        description="Match Paystack payments to orders, clear exceptions and keep evidence attached to every sale."
        actions={
          <Button variant="outline" onClick={() => refresh()} loading={currentQuery.isRefetching}>
            <RefreshCw className="h-4 w-4" /> Refresh
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="surface px-5 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-ink-400">
            Synced today
          </p>
          <p className="mt-1.5 text-2xl font-semibold tracking-[-0.03em] text-ink-950">
            {summaryQuery.data?.synced_today ?? 0}
          </p>
        </div>
        <div className="surface px-5 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-ink-400">
            Matched today
          </p>
          <p className="mt-1.5 text-2xl font-semibold tracking-[-0.03em] text-brand-800">
            {summaryQuery.data?.matched_today ?? 0}
          </p>
        </div>
        <div className="surface px-5 py-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-ink-400">
            Needs review
          </p>
          <p className="mt-1.5 text-2xl font-semibold tracking-[-0.03em] text-amber-700">
            {summaryQuery.data?.needs_review ?? 0}
          </p>
        </div>
      </div>

      {noSession ? (
        <Card>
          <CardBody className="py-12">
            <div className="mx-auto max-w-lg text-center">
              <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-xl bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200">
                <Sparkles className="h-6 w-6" />
              </div>
              <h2 className="mt-5 text-2xl font-semibold tracking-[-0.03em] text-ink-950">
                Start your first reconciliation
              </h2>
              <p className="mt-2 text-sm leading-6 text-ink-500">
                We will pull every successful payment in the range, run the matching tiers and
                surface anything that needs a human decision.
              </p>
              <div className="mt-6 grid gap-3 text-left sm:grid-cols-2">
                <div>
                  <Label htmlFor="from">From</Label>
                  <Input
                    id="from"
                    type="date"
                    value={startDate}
                    onChange={(event) => setStartDate(event.target.value)}
                  />
                </div>
                <div>
                  <Label htmlFor="to">To</Label>
                  <Input
                    id="to"
                    type="date"
                    value={endDate}
                    onChange={(event) => setEndDate(event.target.value)}
                  />
                </div>
              </div>
              <Button
                size="lg"
                className="mt-5 w-full"
                onClick={() => startMutation.mutate()}
                loading={startMutation.isPending}
                disabled={Boolean(startDate) !== Boolean(endDate)}
              >
                Start reconciliation <ArrowRight className="h-4 w-4" />
              </Button>
              <p className="mt-3 text-[11px] text-ink-400">
                Leave the dates blank to use your default reconciliation range.
              </p>
            </div>
          </CardBody>
        </Card>
      ) : currentQuery.isError ? (
        <Alert tone="danger" title="Could not load reconciliation">
          {errorMessage(currentQuery.error)}
        </Alert>
      ) : view ? (
        <>
          <ReconciliationSessionView
            view={view}
            actions={{
              onAccept: (transactionId, orderId) => decide('accept', transactionId, orderId),
              onReject: (transactionId, orderId) => decide('reject', transactionId, orderId),
              onLinkOrder: linkOrder,
              onResolveOrder: resolveOrder,
              onUnflagTransaction: unflagTransaction,
              onUnflagOrder: unflagOrder,
              busyKey,
            }}
          />

          <div className="sticky bottom-4 z-10">
            <div className="flex flex-col items-start justify-between gap-3 rounded-xl border border-ink-800 bg-navy px-5 py-4 text-white shadow-float sm:flex-row sm:items-center">
              <div className="flex flex-wrap items-center gap-4 text-[12px]">
                <span>
                  <span className="font-semibold text-brand-300">
                    {view.session.totals.matched}
                  </span>{' '}
                  matched
                </span>
                <span>
                  <span className="font-semibold text-amber-300">
                    {view.session.totals.unmatched_payments + view.session.totals.unmatched_orders}
                  </span>{' '}
                  unmatched
                </span>
                <span>
                  <span className="font-semibold text-red-300">
                    {view.session.totals.flagged + view.flagged_orders.length}
                  </span>{' '}
                  flagged
                </span>
              </div>
              {view.session.status === 'in_progress' ? (
                <Button
                  className="w-full bg-brand-500 hover:bg-brand-400 sm:w-auto"
                  onClick={() => completeMutation.mutate()}
                  loading={completeMutation.isPending}
                >
                  <CheckCircle2 className="h-4 w-4" /> Complete reconciliation
                </Button>
              ) : (
                <Badge tone="success">Completed {formatDateTime(view.session.completed_at)}</Badge>
              )}
            </div>
          </div>
        </>
      ) : null}

      <Card>
        <CardHeader
          title="Session history"
          description="Past reconciliation periods and their match rates."
          action={<History className="h-4 w-4 text-ink-400" />}
        />
        {sessionsQuery.isLoading ? (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-brand-600" />
          </div>
        ) : sessionsQuery.data?.data.length ? (
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Period</th>
                  <th>Status</th>
                  <th>Matched</th>
                  <th>Unmatched</th>
                  <th>Flagged</th>
                  <th>Completed</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sessionsQuery.data.data.map((session) => {
                  const rate =
                    session.totals.total_transactions > 0
                      ? Math.round(
                          (session.totals.matched / session.totals.total_transactions) * 100,
                        )
                      : null;
                  return (
                    <tr key={session.id}>
                      <td>
                        <p className="text-[12px] font-semibold text-ink-900">
                          {formatDate(session.date_range_start)} –{' '}
                          {formatDate(session.date_range_end)}
                        </p>
                        <p className="text-[11px] text-ink-400">
                          {session.totals.total_transactions} transactions
                        </p>
                      </td>
                      <td>
                        <Badge tone={session.status === 'completed' ? 'success' : 'warning'} dot>
                          {session.status === 'completed' ? 'Completed' : 'In progress'}
                        </Badge>
                      </td>
                      <td>
                        {session.totals.matched}
                        {rate !== null ? (
                          <span className="ml-1 text-[11px] text-ink-400">({rate}%)</span>
                        ) : null}
                      </td>
                      <td>{session.totals.unmatched_payments + session.totals.unmatched_orders}</td>
                      <td>{session.totals.flagged}</td>
                      <td className="text-[12px] text-ink-500">
                        {session.completed_at ? timeAgo(session.completed_at) : '—'}
                      </td>
                      <td>
                        <Link href={`/reconciliation/session/${session.id}`}>
                          <Button variant="ghost" size="sm">
                            View <ArrowRight className="h-3.5 w-3.5" />
                          </Button>
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-5">
            <EmptyState
              icon={<CalendarRange className="h-5 w-5" />}
              title="No sessions yet"
              description="Your completed reconciliation periods will be listed here."
            />
          </div>
        )}
      </Card>
    </div>
  );
}
