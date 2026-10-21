'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeft,
  CalendarDays,
  CheckCircle2,
  CircleSlash,
  CreditCard,
  FileWarning,
  Loader2,
  ReceiptText,
  Settings2,
  ShieldCheck,
  Store,
} from 'lucide-react';
import { apiRequest, errorMessage } from '@/lib/api';
import { cn } from '@/lib/cn';
import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatNumber,
  percent,
  timeAgo,
  titleCase,
} from '@/lib/format';
import type { AdminMerchantDetail } from '@/lib/types';
import {
  CATEGORY_LABELS,
  ONBOARDING_LABELS,
  RECONCILIATION_LABELS,
  STATUS_LABELS,
  TRANSACTION_LABELS,
  TRUST_LABELS,
  TRUST_TONE,
} from '@/lib/constants';
import { PageHeader } from '@/components/ui/page-header';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert } from '@/components/ui/alert';
import { Progress } from '@/components/ui/progress';

export default function AdminMerchantDetailPage() {
  const params = useParams<{ id: string }>();
  const merchantQuery = useQuery({
    queryKey: ['admin', 'merchant', params?.id],
    queryFn: () =>
      apiRequest<AdminMerchantDetail>(`/admin/merchants/${params.id}`, { admin: true }),
    enabled: Boolean(params?.id),
  });

  if (merchantQuery.isLoading) {
    return (
      <div className="flex h-72 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
      </div>
    );
  }

  if (merchantQuery.isError || !merchantQuery.data) {
    return (
      <div className="space-y-5">
        <Link
          href="/admin/merchants"
          className="inline-flex items-center gap-2 text-[12px] font-semibold text-ink-500 hover:text-ink-800"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> All merchants
        </Link>
        <Alert tone="danger" title="Could not load merchant">
          {errorMessage(merchantQuery.error)}
        </Alert>
      </div>
    );
  }

  const merchant = merchantQuery.data;
  const trust = merchant.trust;
  const onboarding = merchant.onboarding;
  const syncProgress =
    onboarding?.initial_sync_total && onboarding.initial_sync_total > 0
      ? Math.min(
          100,
          Math.round((onboarding.initial_sync_processed / onboarding.initial_sync_total) * 100),
        )
      : null;

  return (
    <div className="space-y-6">
      <Link
        href="/admin/merchants"
        className="inline-flex items-center gap-2 text-[12px] font-semibold text-ink-500 hover:text-ink-800"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> All merchants
      </Link>

      <PageHeader
        eyebrow="Merchant detail"
        title={merchant.business_name}
        description={merchant.email ?? merchant.google_email ?? 'No contact email on file'}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={`/admin/merchants/${merchant.id}/data`}
              className="inline-flex h-9 items-center rounded-lg bg-ink-900 px-3 text-[13px] font-semibold text-white hover:bg-ink-800"
            >
              Browse their data
            </Link>
            {merchant.is_active ? (
              <Badge tone="success">
                <CheckCircle2 className="mr-1 h-3 w-3" /> Active
              </Badge>
            ) : (
              <Badge tone="neutral">
                <CircleSlash className="mr-1 h-3 w-3" /> Inactive
              </Badge>
            )}
            {trust ? (
              <span
                className={cn(
                  'rounded-full px-2.5 py-1 text-[9px] font-bold uppercase tracking-wide ring-1 ring-inset',
                  TRUST_TONE[trust.state],
                )}
              >
                {TRUST_LABELS[trust.state]}
              </span>
            ) : (
              <Badge tone="neutral">No trust profile</Badge>
            )}
          </div>
        }
      />

      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <MiniStat label="Transactions" value={merchant.stats.transaction_count} />
        <MiniStat label="Successful" value={merchant.stats.successful_transactions} />
        <MiniStat label="Orders" value={merchant.stats.order_count} />
        <MiniStat label="Customers" value={merchant.stats.customer_count} />
        <MiniStat label="Disputes" value={merchant.stats.dispute_count} />
        <MiniStat
          label="Open disputes"
          value={merchant.stats.open_disputes}
          tone={merchant.stats.open_disputes ? 'amber' : 'default'}
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <Card>
          <CardHeader
            title="Trust profile"
            description="Internal score and signal rates. Never exposed publicly."
            action={<ShieldCheck className="h-4 w-4 text-brand-600" />}
          />
          <CardBody className="space-y-4">
            {trust ? (
              <>
                <div className="flex items-end justify-between gap-4 rounded-xl bg-ink-950 px-4 py-3.5 text-white">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-400">
                      Internal score
                    </p>
                    <p className="mt-1 text-2xl font-semibold tracking-[-0.03em]">
                      {trust.internal_score ?? '—'}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] text-ink-400">Public state</p>
                    <p className="mt-1 text-[12px] font-semibold">{TRUST_LABELS[trust.state]}</p>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2.5">
                  <TrustMetric label="Reconciliation" value={trust.reconciliation_rate} />
                  <TrustMetric label="Fulfillment" value={trust.fulfillment_rate} />
                  <TrustMetric label="Dispute rate" value={trust.dispute_rate} />
                  <TrustMetric label="Win rate" value={trust.dispute_win_rate} />
                  <TrustMetric label="Response time" value={trust.avg_response_time_pct} />
                  <TrustMetric label="Evidence readiness" value={trust.evidence_readiness_avg} />
                </div>
                <div className="grid grid-cols-2 gap-2 text-[11px] text-ink-500">
                  <p>
                    Payments 30d:{' '}
                    <span className="font-medium text-ink-800">{trust.payments_30d ?? '—'}</span>
                  </p>
                  <p>
                    Days on platform:{' '}
                    <span className="font-medium text-ink-800">
                      {trust.days_on_platform ?? '—'}
                    </span>
                  </p>
                  <p>
                    Computed:{' '}
                    <span className="font-medium text-ink-800">
                      {trust.last_computed_at ? timeAgo(trust.last_computed_at) : '—'}
                    </span>
                  </p>
                  <p>
                    Explained:{' '}
                    <span className="font-medium text-ink-800">
                      {trust.explained_at ? timeAgo(trust.explained_at) : '—'}
                    </span>
                  </p>
                </div>
                {trust.explanation ? (
                  <div className="rounded-xl bg-ink-50 p-3.5 text-[11px] leading-5 text-ink-600">
                    {trust.explanation}
                  </div>
                ) : null}
              </>
            ) : (
              <p className="py-8 text-center text-[12px] text-ink-400">
                Trust has not been computed for this merchant yet.
              </p>
            )}
          </CardBody>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Paystack"
              description="Connection state and sync health."
              action={<CreditCard className="h-4 w-4 text-ink-400" />}
            />
            <CardBody className="space-y-3">
              <Row label="Connected" value={merchant.paystack.connected ? 'Yes' : 'No'} />
              <Row
                label="Mode"
                value={merchant.paystack.mode ? titleCase(merchant.paystack.mode) : '—'}
              />
              <Row label="Integration ID" value={merchant.paystack.integration_id ?? '—'} mono />
              <Row label="Connected at" value={formatDateTime(merchant.paystack.connected_at)} />
              <Row
                label="Last sync"
                value={
                  merchant.paystack.last_transaction_sync_at
                    ? timeAgo(merchant.paystack.last_transaction_sync_at)
                    : '—'
                }
              />
              <Row
                label="Webhook"
                value={merchant.paystack.webhook_configured ? 'Configured' : 'Not configured'}
              />
              <Row
                label="Webhook received"
                value={
                  merchant.paystack.webhook_last_received_at
                    ? timeAgo(merchant.paystack.webhook_last_received_at)
                    : '—'
                }
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Onboarding"
              description="Setup progress and initial import state."
              action={<Store className="h-4 w-4 text-ink-400" />}
            />
            <CardBody className="space-y-3">
              {onboarding ? (
                <>
                  <Row label="Current step" value={ONBOARDING_LABELS[onboarding.current_step]} />
                  <Row label="Initial sync" value={titleCase(onboarding.initial_sync_status)} />
                  <div>
                    <div className="flex items-center justify-between text-[11px] text-ink-500">
                      <span>Sync progress</span>
                      <span>
                        {onboarding.initial_sync_processed}
                        {onboarding.initial_sync_total ? ` / ${onboarding.initial_sync_total}` : ''}
                      </span>
                    </div>
                    <Progress value={syncProgress} className="mt-1.5" />
                  </div>
                  <Row
                    label="First reconciliation skipped"
                    value={onboarding.first_reconciliation_skipped ? 'Yes' : 'No'}
                  />
                  <Row
                    label="Completed"
                    value={onboarding.completed_at ? formatDateTime(onboarding.completed_at) : '—'}
                  />
                </>
              ) : (
                <p className="py-4 text-center text-[12px] text-ink-400">No onboarding record.</p>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Settings"
              description="Merchant preferences and public controls."
              action={<Settings2 className="h-4 w-4 text-ink-400" />}
            />
            <CardBody className="space-y-3">
              {merchant.settings ? (
                <>
                  <Row label="Timezone" value={merchant.settings.timezone} />
                  <Row label="Currency" value={merchant.settings.default_currency} />
                  <Row
                    label="Lookback"
                    value={`${merchant.settings.default_reconciliation_range} days`}
                  />
                  <Row
                    label="Public trust page"
                    value={merchant.settings.trust_public_enabled ? 'On' : 'Off'}
                  />
                  <Row
                    label="Embed badge"
                    value={merchant.settings.trust_widget_enabled ? 'On' : 'Off'}
                  />
                  <Row
                    label="Email alerts"
                    value={merchant.settings.notification_email ? 'On' : 'Off'}
                  />
                  <Row
                    label="Auto Tier 1"
                    value={merchant.settings.auto_reconciliation_tier1 ? 'On' : 'Off'}
                  />
                </>
              ) : (
                <p className="py-4 text-center text-[12px] text-ink-400">No settings record.</p>
              )}
            </CardBody>
          </Card>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card className="overflow-hidden">
          <CardHeader
            title="Recent transactions"
            description={`${merchant.stats.transaction_count} total`}
            action={<ReceiptText className="h-4 w-4 text-ink-400" />}
          />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-left">
              <thead>
                <tr className="border-y border-line bg-ink-50/50 text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-400">
                  <th className="px-4 py-2.5">Reference</th>
                  <th className="px-4 py-2.5">Amount</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5">Reconciliation</th>
                  <th className="px-4 py-2.5">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {merchant.recent_transactions.length ? (
                  merchant.recent_transactions.map((transaction) => (
                    <tr key={transaction.id}>
                      <td className="px-4 py-2.5">
                        <p className="font-mono text-[10px] text-ink-700">
                          {transaction.reference}
                        </p>
                        <p className="text-[9px] text-ink-400">
                          {transaction.customer_email ?? 'No email'}
                        </p>
                      </td>
                      <td className="px-4 py-2.5 text-[11px] font-medium text-ink-800">
                        {formatMoney(transaction.amount, transaction.currency)}
                      </td>
                      <td className="px-4 py-2.5 text-[10px] text-ink-600">
                        {TRANSACTION_LABELS[transaction.status]}
                      </td>
                      <td className="px-4 py-2.5 text-[10px] text-ink-600">
                        {RECONCILIATION_LABELS[transaction.reconciliation_status]}
                      </td>
                      <td className="px-4 py-2.5 text-[10px] text-ink-400">
                        {transaction.paid_at
                          ? formatDate(transaction.paid_at)
                          : formatDate(transaction.created_at)}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-[12px] text-ink-400">
                      No transactions.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader
            title="Recent disputes"
            description={`${merchant.stats.open_disputes} open · ${merchant.stats.dispute_count} total`}
            action={<FileWarning className="h-4 w-4 text-ink-400" />}
          />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-left">
              <thead>
                <tr className="border-y border-line bg-ink-50/50 text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-400">
                  <th className="px-4 py-2.5">Reference</th>
                  <th className="px-4 py-2.5">Amount</th>
                  <th className="px-4 py-2.5">Category</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5">Due</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {merchant.recent_disputes.length ? (
                  merchant.recent_disputes.map((dispute) => (
                    <tr key={dispute.id}>
                      <td className="px-4 py-2.5">
                        <p className="font-mono text-[10px] text-ink-700">{dispute.reference}</p>
                        <p className="text-[9px] text-ink-400">{dispute.paystack_dispute_id}</p>
                      </td>
                      <td className="px-4 py-2.5 text-[11px] font-medium text-ink-800">
                        {formatMoney(dispute.amount, dispute.currency)}
                      </td>
                      <td className="px-4 py-2.5 text-[10px] text-ink-600">
                        {dispute.category ? CATEGORY_LABELS[dispute.category] : '—'}
                      </td>
                      <td className="px-4 py-2.5 text-[10px] text-ink-600">
                        {STATUS_LABELS[dispute.status]}
                      </td>
                      <td className="px-4 py-2.5 text-[10px] text-ink-400">
                        {formatDate(dispute.due_at)}
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-[12px] text-ink-400">
                      No disputes.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Trust history"
          description="Snapshots, reasons and state changes."
          action={<CalendarDays className="h-4 w-4 text-ink-400" />}
        />
        <CardBody>
          {merchant.trust_history.length ? (
            <div className="space-y-3">
              {merchant.trust_history
                .slice()
                .reverse()
                .map((snapshot) => (
                  <div
                    key={snapshot.id}
                    className="flex items-start gap-3 rounded-xl border border-line p-3.5"
                  >
                    <span
                      className={cn(
                        'mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide ring-1 ring-inset',
                        TRUST_TONE[snapshot.state],
                      )}
                    >
                      {TRUST_LABELS[snapshot.state]}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-[11px] font-medium text-ink-800">
                        {snapshot.summary ?? snapshot.reason}
                      </p>
                      <p className="mt-0.5 text-[10px] text-ink-400">
                        {formatDateTime(snapshot.created_at)} · score{' '}
                        {snapshot.internal_score ?? '—'}
                      </p>
                    </div>
                  </div>
                ))}
            </div>
          ) : (
            <p className="py-8 text-center text-[12px] text-ink-400">No trust snapshots yet.</p>
          )}
        </CardBody>
      </Card>

      <div className="flex flex-wrap gap-4 rounded-2xl border border-line bg-white px-4 py-3 text-[10px] text-ink-400">
        <span>Created {formatDate(merchant.created_at)}</span>
        <span>Updated {merchant.updated_at ? formatDateTime(merchant.updated_at) : '—'}</span>
        <span>Verified {merchant.is_verified ? 'yes' : 'no'}</span>
        {merchant.deactivated_at ? (
          <span>Deactivated {formatDateTime(merchant.deactivated_at)}</span>
        ) : null}
      </div>
    </div>
  );
}

function MiniStat({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: number;
  tone?: 'default' | 'amber';
}) {
  return (
    <div className="rounded-xl border border-line bg-white px-3.5 py-3">
      <p className="text-[9px] font-semibold uppercase tracking-[0.08em] text-ink-400">{label}</p>
      <p
        className={cn(
          'mt-1 text-lg font-semibold tracking-[-0.02em]',
          tone === 'amber' ? 'text-amber-700' : 'text-ink-950',
        )}
      >
        {formatNumber(value)}
      </p>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line pb-2.5 last:border-0 last:pb-0">
      <span className="text-[11px] text-ink-500">{label}</span>
      <span
        className={cn(
          'max-w-[60%] break-all text-right text-[11px] font-medium text-ink-800',
          mono && 'font-mono text-[10px]',
        )}
      >
        {value}
      </span>
    </div>
  );
}

function TrustMetric({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-lg border border-line px-2.5 py-2">
      <p className="text-[9px] font-semibold uppercase tracking-[0.06em] text-ink-400">{label}</p>
      <p className="mt-0.5 text-[12px] font-semibold text-ink-900">{percent(value, 1)}</p>
    </div>
  );
}
