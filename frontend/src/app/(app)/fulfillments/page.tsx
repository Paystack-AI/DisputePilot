'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, Camera, ImageIcon, Truck } from 'lucide-react';
import { apiList } from '@/lib/api';
import { formatDateTime, titleCase, timeAgo } from '@/lib/format';
import type { Fulfillment, PageMeta } from '@/lib/types';
import { PageHeader } from '@/components/ui/page-header';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { Pagination } from '@/components/ui/pagination';
import { PageSkeleton } from '@/components/ui/skeleton';
import { Tabs } from '@/components/ui/tabs';

const sorts = [
  { value: '-delivery_date', label: 'Latest delivery' },
  { value: 'delivery_date', label: 'Oldest delivery' },
  { value: '-created_at', label: 'Recently logged' },
];

export default function FulfillmentsPage() {
  const [sort, setSort] = useState('-delivery_date');
  const [page, setPage] = useState(1);

  const fulfillmentsQuery = useQuery({
    queryKey: ['fulfillments', 'list', sort, page],
    queryFn: () => apiList<Fulfillment>(`/fulfillments?limit=20&page=${page}&sort=${sort}`),
  });

  const meta: PageMeta | undefined = fulfillmentsQuery.data?.meta;

  const logButton = (
    <Link href="/fulfillments/new">
      <Button>
        <Camera className="h-4 w-4" /> Log fulfillment
      </Button>
    </Link>
  );

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Proof of delivery"
        title="Fulfillments"
        description="Delivery photos, tracking and recipients: the evidence that wins disputes."
        actions={logButton}
      />

      <Tabs
        items={sorts}
        value={sort}
        onChange={(value) => {
          setSort(value);
          setPage(1);
        }}
        className="w-fit"
      />

      {fulfillmentsQuery.isLoading ? (
        <PageSkeleton />
      ) : fulfillmentsQuery.data?.data.length ? (
        <div className="table-shell overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th>Type</th>
                <th>Delivered</th>
                <th>Recipient</th>
                <th>Tracking</th>
                <th>Evidence</th>
                <th>Payment</th>
                <th>Logged</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {fulfillmentsQuery.data.data.map((fulfillment) => (
                <tr key={fulfillment.id}>
                  <td>
                    <Link
                      href={`/fulfillments/${fulfillment.id}`}
                      className="flex items-center gap-2.5 font-semibold text-ink-900 hover:text-brand-700"
                    >
                      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
                        <Truck className="h-3.5 w-3.5" />
                      </span>
                      {titleCase(fulfillment.type)}
                    </Link>
                  </td>
                  <td className="text-[12px] text-ink-600">
                    {formatDateTime(fulfillment.delivery_date)}
                  </td>
                  <td className="text-[12px] text-ink-700">{fulfillment.recipient_name ?? '—'}</td>
                  <td className="font-mono text-[11px] text-ink-500">
                    {fulfillment.tracking_number ?? '—'}
                  </td>
                  <td>
                    {fulfillment.files.length ? (
                      <Badge tone="success">
                        <ImageIcon className="h-3 w-3" /> {fulfillment.files.length} photo
                        {fulfillment.files.length === 1 ? '' : 's'}
                      </Badge>
                    ) : (
                      <Badge tone="warning">No photos</Badge>
                    )}
                  </td>
                  <td>
                    <Badge tone={fulfillment.transaction_id ? 'success' : 'neutral'}>
                      {fulfillment.transaction_id ? 'Linked' : 'Not linked'}
                    </Badge>
                  </td>
                  <td className="text-[12px] text-ink-500">{timeAgo(fulfillment.created_at)}</td>
                  <td>
                    <Link href={`/fulfillments/${fulfillment.id}`}>
                      <Button variant="ghost" size="sm" aria-label="Open fulfillment">
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
          icon={<Truck className="h-5 w-5" />}
          title="No fulfillments yet"
          description="Log a delivery, pickup or completed service as soon as it happens, with photos."
          action={logButton}
        />
      )}
    </div>
  );
}
