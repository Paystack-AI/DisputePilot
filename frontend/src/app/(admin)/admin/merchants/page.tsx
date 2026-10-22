'use client';

import { useDeferredValue, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, CheckCircle2, CircleSlash, Loader2, Search, Store, X } from 'lucide-react';
import { apiList, errorMessage } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDate, formatNumber, titleCase } from '@/lib/format';
import type { AdminMerchantListItem } from '@/lib/types';
import { ONBOARDING_LABELS } from '@/lib/constants';
import { PageHeader } from '@/components/ui/page-header';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Alert } from '@/components/ui/alert';
import { Pagination } from '@/components/ui/pagination';
import { EmptyState } from '@/components/ui/empty-state';
import { TRUST_LABELS, TRUST_TONE } from '@/lib/constants';

export default function AdminMerchantsPage() {
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search);
  const [page, setPage] = useState(1);

  const merchantsQuery = useQuery({
    queryKey: ['admin', 'merchants', deferredSearch, page],
    queryFn: () =>
      apiList<AdminMerchantListItem>(
        `/admin/merchants?page=${page}&limit=20${deferredSearch ? `&search=${encodeURIComponent(deferredSearch)}` : ''}`,
        { admin: true },
      ),
  });

  const merchants = merchantsQuery.data?.data ?? [];
  const meta = merchantsQuery.data?.meta;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Operator console"
        title="Merchants"
        description="Every workspace, newest first. Search by business name or email."
        actions={
          <Badge tone="neutral">{meta ? `${formatNumber(meta.total)} total` : 'Loading'}</Badge>
        }
      />

      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
        <Input
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(1);
          }}
          placeholder="Search business name or email"
          className="pl-9 pr-9"
        />
        {search ? (
          <button
            type="button"
            onClick={() => {
              setSearch('');
              setPage(1);
            }}
            className="absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-lg text-ink-400 hover:bg-ink-50 hover:text-ink-700"
            aria-label="Clear search"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>

      {merchantsQuery.isError ? (
        <Alert tone="danger" title="Could not load merchants">
          {errorMessage(merchantsQuery.error)}
        </Alert>
      ) : null}

      <Card className="overflow-hidden">
        {merchantsQuery.isLoading ? (
          <div className="flex h-56 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-brand-600" />
          </div>
        ) : merchants.length ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] border-collapse text-left">
                <thead>
                  <tr className="border-b border-line bg-ink-50/50 text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-400">
                    <th className="px-4 py-3">Merchant</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Paystack</th>
                    <th className="px-4 py-3">Onboarding</th>
                    <th className="px-4 py-3">Trust</th>
                    <th className="px-4 py-3 text-right">Transactions</th>
                    <th className="px-4 py-3 text-right">Disputes</th>
                    <th className="px-4 py-3">Joined</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {merchants.map((merchant) => (
                    <tr key={merchant.id} className="transition hover:bg-ink-50/40">
                      <td className="px-4 py-3.5">
                        <Link
                          href={`/admin/merchants/${merchant.id}`}
                          className="flex items-center gap-2.5"
                        >
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-[10px] font-bold text-brand-700">
                            {merchant.business_name.slice(0, 2).toUpperCase()}
                          </span>
                          <div className="min-w-0">
                            <p className="truncate text-[12px] font-semibold text-ink-900">
                              {merchant.business_name}
                            </p>
                            <p className="truncate text-[10px] text-ink-400">
                              {merchant.email ?? 'No email'}
                            </p>
                          </div>
                        </Link>
                      </td>
                      <td className="px-4 py-3.5">
                        {merchant.is_active ? (
                          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-brand-700">
                            <CheckCircle2 className="h-3 w-3" /> Active
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-ink-400">
                            <CircleSlash className="h-3 w-3" /> Inactive
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3.5">
                        {merchant.paystack_connected ? (
                          <Badge tone={merchant.paystack_mode === 'live' ? 'success' : 'warning'}>
                            {merchant.paystack_mode
                              ? titleCase(merchant.paystack_mode)
                              : 'Connected'}
                          </Badge>
                        ) : (
                          <Badge tone="neutral">Not connected</Badge>
                        )}
                      </td>
                      <td className="px-4 py-3.5">
                        <p className="text-[11px] font-medium text-ink-700">
                          {merchant.onboarding_completed
                            ? 'Complete'
                            : merchant.onboarding_step
                              ? ONBOARDING_LABELS[merchant.onboarding_step]
                              : 'Not started'}
                        </p>
                      </td>
                      <td className="px-4 py-3.5">
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
                          <span className="text-[10px] text-ink-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3.5 text-right text-[11px] font-medium text-ink-700">
                        {formatNumber(merchant.transaction_count)}
                      </td>
                      <td className="px-4 py-3.5 text-right text-[11px] font-medium text-ink-700">
                        {formatNumber(merchant.dispute_count)}
                      </td>
                      <td className="px-4 py-3.5 text-[10px] text-ink-500">
                        {formatDate(merchant.created_at)}
                      </td>
                      <td className="px-4 py-3.5">
                        <Link
                          href={`/admin/merchants/${merchant.id}`}
                          className="flex h-7 w-7 items-center justify-center rounded-lg text-ink-300 hover:bg-surface hover:text-ink-800"
                          aria-label={`Open ${merchant.business_name}`}
                        >
                          <ArrowRight className="h-3.5 w-3.5" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination meta={meta} onPageChange={setPage} />
          </>
        ) : (
          <EmptyState
            icon={<Store className="h-5 w-5" />}
            title={search ? 'No merchants match your search' : 'No merchants yet'}
            description={
              search
                ? 'Try a different business name or email.'
                : 'Merchants appear here as soon as they create a workspace.'
            }
          />
        )}
      </Card>
    </div>
  );
}
