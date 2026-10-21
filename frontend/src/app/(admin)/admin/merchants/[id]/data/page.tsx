'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Download, Eye, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { apiBlob, apiList, apiRequest, errorMessage } from '@/lib/api';
import { formatDate, formatDateTime, formatMoney, percent, titleCase } from '@/lib/format';
import type {
  AdminMerchantDetail,
  CustomerSummary,
  DisputeSummary,
  Fulfillment,
  Order,
  PageMeta,
  ReconciliationSession,
  Transaction,
} from '@/lib/types';
import {
  ORDER_STATUS_LABELS,
  RECONCILIATION_LABELS,
  STATUS_LABELS,
  TRANSACTION_LABELS,
} from '@/lib/constants';
import { PageHeader } from '@/components/ui/page-header';
import { Alert } from '@/components/ui/alert';
import { Badge, statusTone } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Pagination } from '@/components/ui/pagination';
import { Tabs } from '@/components/ui/tabs';

type Section =
  'transactions' | 'orders' | 'customers' | 'fulfillments' | 'disputes' | 'reconciliation';

const SECTIONS: { value: Section; label: string; path: string }[] = [
  { value: 'transactions', label: 'Transactions', path: '/transactions' },
  { value: 'orders', label: 'Orders', path: '/orders' },
  { value: 'customers', label: 'Customers', path: '/customers' },
  { value: 'fulfillments', label: 'Fulfillments', path: '/fulfillments' },
  { value: 'disputes', label: 'Disputes', path: '/disputes' },
  { value: 'reconciliation', label: 'Reconciliation', path: '/reconciliation/sessions' },
];

/** Everything the merchant sees, read-only, through /admin/merchants/{id}/* */
export default function AdminMerchantDataPage() {
  const params = useParams<{ id: string }>();
  const base = `/admin/merchants/${params.id}`;
  const [section, setSection] = useState<Section>('transactions');
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState<{ title: string; path: string } | null>(null);

  const merchantQuery = useQuery({
    queryKey: ['admin', 'merchant', params.id],
    queryFn: () => apiRequest<AdminMerchantDetail>(base, { admin: true }),
    enabled: Boolean(params.id),
  });

  const current = SECTIONS.find((item) => item.value === section)!;
  const listQuery = useQuery({
    queryKey: ['admin', 'merchant', params.id, section, page],
    queryFn: () =>
      apiList<unknown>(`${base}${current.path}?limit=20&page=${page}`, { admin: true }),
    enabled: Boolean(params.id),
  });

  const downloadPdf = async (dispute: DisputeSummary) => {
    try {
      const blob = await apiBlob(`${base}/disputes/${dispute.id}/evidence-pdf`, { admin: true });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `evidence-${dispute.paystack_dispute_id}.pdf`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(errorMessage(error));
    }
  };

  const view = (title: string, path: string) => setDetail({ title, path: `${base}${path}` });
  const rows = listQuery.data?.data ?? [];
  const meta: PageMeta | undefined = listQuery.data?.meta;

  return (
    <div className="space-y-6">
      <Link
        href={`/admin/merchants/${params.id}`}
        className="inline-flex items-center gap-2 text-[12px] font-semibold text-ink-500 hover:text-ink-800"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Merchant overview
      </Link>

      <PageHeader
        eyebrow="Read-only view"
        title={merchantQuery.data?.business_name ?? 'Merchant data'}
        description="Exactly what the merchant sees in their workspace. Nothing here can change their data."
      />

      <Tabs
        items={SECTIONS.map(({ value, label }) => ({ value, label }))}
        value={section}
        onChange={(value) => {
          setSection(value as Section);
          setPage(1);
          setDetail(null);
        }}
        className="w-fit"
      />

      {listQuery.isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-brand-600" />
        </div>
      ) : listQuery.isError ? (
        <Alert tone="danger" title="Could not load">
          {errorMessage(listQuery.error)}
        </Alert>
      ) : rows.length ? (
        <div className="table-shell overflow-x-auto">
          <table className="table-base">
            {section === 'transactions' ? (
              <TransactionRows
                rows={rows as Transaction[]}
                onView={(t) =>
                  view(t.reference, `/transactions/${encodeURIComponent(t.reference)}`)
                }
              />
            ) : section === 'orders' ? (
              <OrderRows
                rows={rows as Order[]}
                onView={(o) => view(`Order ${o.order_number ?? ''}`, `/orders/${o.id}`)}
              />
            ) : section === 'customers' ? (
              <CustomerRows
                rows={rows as CustomerSummary[]}
                onView={(c) =>
                  view(c.name ?? c.email ?? 'Customer', `/customers/${c.id}/ledger?limit=50`)
                }
              />
            ) : section === 'fulfillments' ? (
              <FulfillmentRows
                rows={rows as Fulfillment[]}
                onView={(f) => view(titleCase(f.type), `/fulfillments/${f.id}`)}
              />
            ) : section === 'disputes' ? (
              <DisputeRows
                rows={rows as DisputeSummary[]}
                onView={(d) => view(d.paystack_dispute_id, `/disputes/${d.id}`)}
                onPdf={downloadPdf}
              />
            ) : (
              <SessionRows
                rows={rows as ReconciliationSession[]}
                onView={(s) => view('Reconciliation session', `/reconciliation/sessions/${s.id}`)}
              />
            )}
          </table>
          <Pagination meta={meta} onPageChange={setPage} />
        </div>
      ) : (
        <EmptyState title={`No ${current.label.toLowerCase()} yet`} />
      )}

      {detail ? <DetailPanel {...detail} onClose={() => setDetail(null)} /> : null}
    </div>
  );
}

/** The raw response of one detail route, for inspecting what the merchant's screen gets */
function DetailPanel({
  title,
  path,
  onClose,
}: {
  title: string;
  path: string;
  onClose: () => void;
}) {
  const isList = path.includes('/ledger');
  const query = useQuery({
    queryKey: ['admin', 'detail', path],
    queryFn: () =>
      isList
        ? apiList<unknown>(path, { admin: true }).then((res) => res.data)
        : apiRequest<unknown>(path, { admin: true }),
  });
  return (
    <div className="surface overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
        <p className="text-[14px] font-semibold text-ink-900">{title}</p>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
      {query.isLoading ? (
        <div className="flex h-32 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-brand-600" />
        </div>
      ) : query.isError ? (
        <div className="p-5">
          <Alert tone="danger">{errorMessage(query.error)}</Alert>
        </div>
      ) : (
        <pre className="max-h-[480px] overflow-auto bg-ink-950 p-5 text-[11px] leading-5 text-ink-100 scrollbar-thin">
          {JSON.stringify(query.data, null, 2)}
        </pre>
      )}
    </div>
  );
}

function ViewButton({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="ghost" size="sm" onClick={onClick} aria-label="View detail">
      <Eye className="h-3.5 w-3.5" />
    </Button>
  );
}

function TransactionRows({
  rows,
  onView,
}: {
  rows: Transaction[];
  onView: (t: Transaction) => void;
}) {
  return (
    <>
      <thead>
        <tr>
          <th>Reference</th>
          <th>Customer</th>
          <th>Amount</th>
          <th>Status</th>
          <th>Reconciliation</th>
          <th>Paid</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((t) => (
          <tr key={t.id}>
            <td className="font-mono text-[12px] font-semibold text-ink-900">{t.reference}</td>
            <td className="text-[12px] text-ink-600">{t.customer_email ?? '—'}</td>
            <td className="font-semibold text-ink-900">{formatMoney(t.amount, t.currency)}</td>
            <td>
              <Badge tone={statusTone(t.status)}>{TRANSACTION_LABELS[t.status]}</Badge>
            </td>
            <td>
              <Badge tone={statusTone(t.reconciliation_status)}>
                {RECONCILIATION_LABELS[t.reconciliation_status]}
              </Badge>
            </td>
            <td className="text-[12px] text-ink-500">{formatDateTime(t.paid_at)}</td>
            <td>
              <ViewButton onClick={() => onView(t)} />
            </td>
          </tr>
        ))}
      </tbody>
    </>
  );
}

function OrderRows({ rows, onView }: { rows: Order[]; onView: (o: Order) => void }) {
  return (
    <>
      <thead>
        <tr>
          <th>Order</th>
          <th>Customer</th>
          <th>Amount</th>
          <th>Status</th>
          <th>Payment</th>
          <th>Created</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((o) => (
          <tr key={o.id}>
            <td className="font-semibold text-ink-900">{o.order_number ?? '—'}</td>
            <td className="text-[12px] text-ink-600">{o.customer?.email ?? '—'}</td>
            <td className="font-semibold text-ink-900">{formatMoney(o.amount, o.currency)}</td>
            <td>
              <Badge tone={statusTone(o.status)}>{ORDER_STATUS_LABELS[o.status]}</Badge>
            </td>
            <td>
              <Badge tone={o.is_linked ? 'success' : 'neutral'}>
                {o.is_linked ? 'Linked' : 'Awaiting'}
              </Badge>
            </td>
            <td className="text-[12px] text-ink-500">{formatDate(o.created_at)}</td>
            <td>
              <ViewButton onClick={() => onView(o)} />
            </td>
          </tr>
        ))}
      </tbody>
    </>
  );
}

function CustomerRows({
  rows,
  onView,
}: {
  rows: CustomerSummary[];
  onView: (c: CustomerSummary) => void;
}) {
  return (
    <>
      <thead>
        <tr>
          <th>Customer</th>
          <th>Payments</th>
          <th>Reconciled</th>
          <th>Disputes</th>
          <th>Last payment</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.id}>
            <td>
              <p className="text-[12px] font-semibold text-ink-900">{c.name ?? '—'}</p>
              <p className="text-[11px] text-ink-400">{c.email ?? 'No email'}</p>
            </td>
            <td className="tabular-nums">{c.payment_count}</td>
            <td>{percent(c.reconciled_pct)}</td>
            <td className="tabular-nums">{c.dispute_count}</td>
            <td className="text-[12px] text-ink-500">{formatDate(c.last_payment_at)}</td>
            <td>
              <ViewButton onClick={() => onView(c)} />
            </td>
          </tr>
        ))}
      </tbody>
    </>
  );
}

function FulfillmentRows({
  rows,
  onView,
}: {
  rows: Fulfillment[];
  onView: (f: Fulfillment) => void;
}) {
  return (
    <>
      <thead>
        <tr>
          <th>Type</th>
          <th>Delivered</th>
          <th>Recipient</th>
          <th>Photos</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((f) => (
          <tr key={f.id}>
            <td className="font-semibold text-ink-900">{titleCase(f.type)}</td>
            <td className="text-[12px] text-ink-500">{formatDateTime(f.delivery_date)}</td>
            <td className="text-[12px] text-ink-600">{f.recipient_name ?? '—'}</td>
            <td className="tabular-nums">{f.files.length}</td>
            <td>
              <ViewButton onClick={() => onView(f)} />
            </td>
          </tr>
        ))}
      </tbody>
    </>
  );
}

function DisputeRows({
  rows,
  onView,
  onPdf,
}: {
  rows: DisputeSummary[];
  onView: (d: DisputeSummary) => void;
  onPdf: (d: DisputeSummary) => void;
}) {
  return (
    <>
      <thead>
        <tr>
          <th>Dispute</th>
          <th>Amount</th>
          <th>Status</th>
          <th>Readiness</th>
          <th>Due</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((d) => (
          <tr key={d.id}>
            <td>
              <p className="font-mono text-[12px] font-semibold text-ink-900">
                {d.paystack_dispute_id}
              </p>
              <p className="text-[11px] text-ink-400">{d.transaction_reference}</p>
            </td>
            <td className="font-semibold text-ink-900">{formatMoney(d.amount, d.currency)}</td>
            <td>
              <Badge tone={statusTone(d.status)}>{STATUS_LABELS[d.status]}</Badge>
            </td>
            <td className="tabular-nums">{d.readiness?.score ?? '—'}</td>
            <td className="text-[12px] text-ink-500">{formatDateTime(d.due_at)}</td>
            <td className="flex gap-1">
              <ViewButton onClick={() => onView(d)} />
              {d.evidence_state === 'ready' ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onPdf(d)}
                  aria-label="Evidence PDF"
                >
                  <Download className="h-3.5 w-3.5" />
                </Button>
              ) : null}
            </td>
          </tr>
        ))}
      </tbody>
    </>
  );
}

function SessionRows({
  rows,
  onView,
}: {
  rows: ReconciliationSession[];
  onView: (s: ReconciliationSession) => void;
}) {
  return (
    <>
      <thead>
        <tr>
          <th>Range</th>
          <th>Status</th>
          <th>Matched</th>
          <th>Needs review</th>
          <th>Started</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((s) => (
          <tr key={s.id}>
            <td className="text-[12px] text-ink-700">
              {formatDate(s.date_range_start)} – {formatDate(s.date_range_end)}
            </td>
            <td>
              <Badge tone={s.status === 'completed' ? 'success' : 'warning'}>
                {titleCase(s.status)}
              </Badge>
            </td>
            <td className="tabular-nums">
              {s.totals.matched}/{s.totals.total_transactions}
            </td>
            <td className="tabular-nums">
              {s.totals.suggested + s.totals.unmatched_payments + s.totals.flagged}
            </td>
            <td className="text-[12px] text-ink-500">{formatDateTime(s.created_at)}</td>
            <td>
              <ViewButton onClick={() => onView(s)} />
            </td>
          </tr>
        ))}
      </tbody>
    </>
  );
}
