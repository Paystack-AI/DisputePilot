'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { href, rowClick } from '@/lib/links';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, CreditCard, RefreshCcw } from 'lucide-react';
import { toast } from 'sonner';
import { apiList, apiRequest, errorMessage } from '@/lib/api';
import {
  channelLabel,
  formatDateTime,
  formatMoney,
  queryString,
  timeAgo,
  titleCase,
} from '@/lib/format';
import type { PageMeta, ReconciliationStatus, Transaction } from '@/lib/types';
import { RECONCILIATION_LABELS, TRANSACTION_LABELS } from '@/lib/constants';
import { PageHeader } from '@/components/ui/page-header';
import { Button } from '@/components/ui/button';
import { Input, Select } from '@/components/ui/input';
import { Badge, statusTone } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { Pagination } from '@/components/ui/pagination';
import { PageSkeleton } from '@/components/ui/skeleton';
import { Tabs } from '@/components/ui/tabs';
import { useUrlParam } from '@/lib/use-url-param';

const reconciliationFilters: ('all' | ReconciliationStatus)[] = [
  'all',
  'unmatched',
  'auto_matched',
  'manually_matched',
  'flagged',
];

export default function TransactionsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [reconciliationParam, setReconciliation] = useUrlParam('reconciliation_status', 'all');
  const reconciliation = reconciliationParam as 'all' | ReconciliationStatus;
  const [status, setStatus] = useUrlParam('status', '');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [page, setPage] = useState(1);

  const transactionsQuery = useQuery({
    queryKey: ['transactions', 'list', reconciliation, status, dateFrom, dateTo, page],
    queryFn: () =>
      apiList<Transaction>(
        `/transactions${queryString({
          limit: 20,
          page,
          reconciliation_status: reconciliation === 'all' ? undefined : reconciliation,
          status: status || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        })}`,
      ),
  });

  const syncMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ status: string; last_sync_at: string | null }>('/transactions/sync', {
        method: 'POST',
      }),
    onSuccess: () => {
      toast.success('Sync started. New payments will appear shortly.');
      queryClient.invalidateQueries({ queryKey: ['transactions'] });
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const meta: PageMeta | undefined = transactionsQuery.data?.meta;
  const filtered = reconciliation !== 'all' || status || dateFrom || dateTo;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Payment ledger"
        title="Transactions"
        description="Every Paystack payment we have synced, with its match and dispute readiness."
        actions={
          <Button onClick={() => syncMutation.mutate()} loading={syncMutation.isPending}>
            <RefreshCcw className="h-4 w-4" /> Sync from Paystack
          </Button>
        }
      />

      <div className="flex flex-col justify-between gap-3 xl:flex-row xl:items-center">
        <Tabs
          items={reconciliationFilters.map((value) => ({
            value,
            label: value === 'all' ? 'All' : RECONCILIATION_LABELS[value],
          }))}
          value={reconciliation}
          onChange={(value) => {
            setReconciliation(value as typeof reconciliation);
            setPage(1);
          }}
        />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <Select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(1);
            }}
            aria-label="Payment status"
          >
            <option value="">Any status</option>
            {Object.entries(TRANSACTION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
          <Input
            type="date"
            value={dateFrom}
            onChange={(event) => {
              setDateFrom(event.target.value);
              setPage(1);
            }}
            aria-label="From date"
          />
          <Input
            type="date"
            value={dateTo}
            onChange={(event) => {
              setDateTo(event.target.value);
              setPage(1);
            }}
            aria-label="To date"
          />
        </div>
      </div>

      {transactionsQuery.isLoading ? (
        <PageSkeleton />
      ) : transactionsQuery.data?.data.length ? (
        <div className="table-shell overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th>Reference</th>
                <th>Customer</th>
                <th>Amount</th>
                <th>Channel</th>
                <th>Status</th>
                <th>Reconciliation</th>
                <th>Readiness</th>
                <th>Paid</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {transactionsQuery.data.data.map((transaction) => (
                <tr
                  key={transaction.id}
                  className="row-link"
                  onClick={rowClick(router.push, href.transaction(transaction.reference))}
                >
                  <td>
                    <Link
                      href={`/transactions/${encodeURIComponent(transaction.reference)}`}
                      className="font-mono text-[12px] font-semibold text-ink-900 hover:text-brand-700"
                    >
                      {transaction.reference}
                    </Link>
                    {transaction.order ? (
                      <Link
                        href={`/orders/${transaction.order.id}`}
                        className="mt-0.5 block text-[11px] text-ink-500 hover:text-brand-600 hover:underline"
                      >
                        Order {transaction.order.order_number ?? '—'}
                      </Link>
                    ) : null}
                  </td>
                  <td>
                    {transaction.customer ? (
                      <Link
                        href={`/customers/${transaction.customer.id}`}
                        className="block text-[12px] font-medium text-ink-800 hover:text-brand-600 hover:underline"
                      >
                        {transaction.customer.name ?? transaction.customer_name ?? 'Customer'}
                      </Link>
                    ) : (
                      <p className="text-[12px] font-medium text-ink-800">
                        {transaction.customer_name ?? '—'}
                      </p>
                    )}
                    <p className="text-[11px] text-ink-400">
                      {transaction.customer_email ?? 'No email'}
                    </p>
                  </td>
                  <td className="font-semibold text-ink-900">
                    {formatMoney(transaction.amount, transaction.currency)}
                  </td>
                  <td className="text-[12px] text-ink-500">{channelLabel(transaction.channel)}</td>
                  <td>
                    <Badge tone={statusTone(transaction.status)}>
                      {TRANSACTION_LABELS[transaction.status]}
                    </Badge>
                  </td>
                  <td>
                    <Badge tone={statusTone(transaction.reconciliation_status)}>
                      {RECONCILIATION_LABELS[transaction.reconciliation_status]}
                    </Badge>
                  </td>
                  <td className="text-[12px] text-ink-600">
                    {transaction.readiness ? (
                      <span className="font-semibold tabular-nums">
                        {transaction.readiness.score}
                        <span className="ml-1 font-normal text-ink-400">
                          {titleCase(transaction.readiness.label)}
                        </span>
                      </span>
                    ) : (
                      <span className="text-ink-400">—</span>
                    )}
                  </td>
                  <td
                    className="text-[12px] text-ink-500"
                    title={formatDateTime(transaction.paid_at)}
                  >
                    {timeAgo(transaction.paid_at)}
                  </td>
                  <td>
                    <Link href={`/transactions/${encodeURIComponent(transaction.reference)}`}>
                      <Button variant="ghost" size="sm" aria-label="Open transaction">
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
          icon={<CreditCard className="h-5 w-5" />}
          title={filtered ? 'No matching transactions' : 'No transactions yet'}
          description="Payments arrive from Paystack by webhook and on each sync."
          action={
            <Button onClick={() => syncMutation.mutate()} loading={syncMutation.isPending}>
              <RefreshCcw className="h-4 w-4" /> Sync now
            </Button>
          }
        />
      )}
    </div>
  );
}
