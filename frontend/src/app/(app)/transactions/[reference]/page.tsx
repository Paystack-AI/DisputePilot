'use client';

import { useDeferredValue, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Camera,
  CheckCircle2,
  CircleAlert,
  ExternalLink,
  Flag,
  Gavel,
  Link2,
  Search,
  Truck,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiList, apiRequest, errorMessage } from '@/lib/api';
import { channelLabel, formatDate, formatDateTime, formatMoney, titleCase } from '@/lib/format';
import type { Order, TransactionDetail } from '@/lib/types';
import {
  ORDER_STATUS_LABELS,
  RECONCILIATION_LABELS,
  STATUS_LABELS,
  TRANSACTION_LABELS,
} from '@/lib/constants';
import { cn } from '@/lib/cn';
import { PageSkeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import { Badge, statusTone } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Avatar } from '@/components/ui/avatar';
import { Modal } from '@/components/ui/modal';
import { FieldHint, Input, Label, Textarea } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';

export default function TransactionDetailPage() {
  const params = useParams<{ reference: string }>();
  const reference = decodeURIComponent(params.reference);
  const path = `/transactions/${encodeURIComponent(reference)}`;
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<'flag' | 'match' | null>(null);
  const [reason, setReason] = useState('');

  const transactionQuery = useQuery({
    queryKey: ['transactions', 'detail', reference],
    queryFn: () => apiRequest<TransactionDetail>(path),
    enabled: Boolean(reference),
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['transactions'] });
    queryClient.invalidateQueries({ queryKey: ['orders'] });
    queryClient.invalidateQueries({ queryKey: ['order'] });
    queryClient.invalidateQueries({ queryKey: ['reconciliation'] });
    queryClient.invalidateQueries({ queryKey: ['dashboard'] });
  };

  const flagMutation = useMutation({
    mutationFn: (flagReason: string) =>
      apiRequest(`${path}/flag`, { method: 'PUT', body: { reason: flagReason } }),
    onSuccess: () => {
      toast.success('Payment flagged for review');
      setDialog(null);
      setReason('');
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const unflagMutation = useMutation({
    mutationFn: () => apiRequest(`${path}/unflag`, { method: 'PUT' }),
    onSuccess: () => {
      toast.success('Flag removed');
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const matchMutation = useMutation({
    mutationFn: (orderId: string) =>
      apiRequest(`${path}/match`, { method: 'PUT', body: { order_id: orderId } }),
    onSuccess: () => {
      toast.success('Payment matched to the order');
      setDialog(null);
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (transactionQuery.isLoading) return <PageSkeleton />;
  if (transactionQuery.isError || !transactionQuery.data) {
    return (
      <div className="space-y-5">
        <Link href="/transactions">
          <Button variant="outline">
            <ArrowLeft className="h-4 w-4" /> Back to transactions
          </Button>
        </Link>
        <Alert tone="danger" title="Could not load this transaction">
          {errorMessage(transactionQuery.error)}
        </Alert>
      </div>
    );
  }

  const transaction = transactionQuery.data;
  const flagged = transaction.reconciliation_status === 'flagged';
  const canMatch = !transaction.order && transaction.status === 'success';

  return (
    <div className="space-y-6">
      <Link
        href="/transactions"
        className="inline-flex items-center gap-2 text-[12px] font-semibold text-ink-500 hover:text-ink-800"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> All transactions
      </Link>

      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={statusTone(transaction.status)}>
              {TRANSACTION_LABELS[transaction.status]}
            </Badge>
            <Badge tone={statusTone(transaction.reconciliation_status)}>
              {RECONCILIATION_LABELS[transaction.reconciliation_status]}
            </Badge>
            {transaction.dispute ? <Badge tone="danger">Disputed</Badge> : null}
          </div>
          <h1 className="mt-3 break-all font-mono text-[26px] font-semibold tracking-[-0.03em] text-ink-950">
            {transaction.reference}
          </h1>
          <p className="mt-1 text-sm text-ink-500">
            {formatMoney(transaction.amount, transaction.currency)} ·{' '}
            {channelLabel(transaction.channel)} · paid {formatDateTime(transaction.paid_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          {canMatch ? (
            <Button onClick={() => setDialog('match')}>
              <Link2 className="h-4 w-4" /> Match to order
            </Button>
          ) : null}
          {transaction.order ? (
            <Link href={`/fulfillments/new?order=${transaction.order.id}`}>
              <Button variant="outline">
                <Camera className="h-4 w-4" /> Log fulfillment
              </Button>
            </Link>
          ) : null}
          {flagged ? (
            <Button
              variant="outline"
              onClick={() => unflagMutation.mutate()}
              loading={unflagMutation.isPending}
            >
              <XCircle className="h-4 w-4" /> Remove flag
            </Button>
          ) : (
            <Button variant="ghost" onClick={() => setDialog('flag')}>
              <Flag className="h-4 w-4" /> Flag
            </Button>
          )}
        </div>
      </div>

      {transaction.flag_reason ? (
        <Alert tone="danger" title={`Flagged ${formatDateTime(transaction.flagged_at)}`}>
          {transaction.flag_reason}
        </Alert>
      ) : null}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.4fr_1fr]">
        <div className="space-y-6">
          <Card>
            <CardHeader title="Payment details" description="As reported by Paystack." />
            <CardBody className="space-y-3 text-[13px]">
              <Row label="Paystack ID" value={transaction.paystack_transaction_id} mono />
              <Row label="Amount" value={formatMoney(transaction.amount, transaction.currency)} />
              <Row
                label="Paystack fees"
                value={formatMoney(transaction.paystack_fees, transaction.currency)}
              />
              <Row label="Channel" value={channelLabel(transaction.channel)} />
              <Row label="Paid" value={formatDateTime(transaction.paid_at)} />
              <Row label="Reconciled" value={formatDateTime(transaction.reconciled_at)} />
              <Row label="Last synced" value={formatDateTime(transaction.synced_at)} />
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Matched order"
              description="The sale this payment settles."
              action={
                canMatch ? (
                  <Button variant="outline" size="sm" onClick={() => setDialog('match')}>
                    <Link2 className="h-3.5 w-3.5" /> Match
                  </Button>
                ) : null
              }
            />
            {transaction.order ? (
              <CardBody className="space-y-3 text-[13px]">
                <div className="flex items-center justify-between gap-3">
                  <Link
                    href={`/orders/${transaction.order.id}`}
                    className="font-semibold text-ink-900 hover:text-brand-700"
                  >
                    Order {transaction.order.order_number ?? '—'}
                  </Link>
                  <Badge tone={statusTone(transaction.order.status)}>
                    {ORDER_STATUS_LABELS[transaction.order.status]}
                  </Badge>
                </div>
                <Row
                  label="Amount"
                  value={formatMoney(transaction.order.amount, transaction.order.currency)}
                />
                <Row label="Source" value={titleCase(transaction.order.source)} />
                <Row label="Description" value={transaction.order.description ?? '—'} />
                {transaction.order.amount !== transaction.amount ? (
                  <Alert tone="warning">
                    The order amount differs from the payment by{' '}
                    {formatMoney(
                      Math.abs(transaction.order.amount - transaction.amount),
                      transaction.currency,
                    )}
                    .
                  </Alert>
                ) : null}
              </CardBody>
            ) : (
              <div className="px-5 py-8 text-center text-[13px] text-ink-400">
                No order is matched to this payment yet.
              </div>
            )}
          </Card>

          <Card>
            <CardHeader title="Fulfillment evidence" />
            {transaction.fulfillments.length ? (
              <div className="divide-y divide-line">
                {transaction.fulfillments.map((fulfillment) => (
                  <Link
                    key={fulfillment.id}
                    href={`/fulfillments/${fulfillment.id}`}
                    className="flex items-center justify-between gap-3 px-5 py-3.5 hover:bg-ink-50/60"
                  >
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
                        <Truck className="h-4 w-4" />
                      </div>
                      <div>
                        <p className="text-[13px] font-semibold text-ink-900">
                          {titleCase(fulfillment.type)}
                        </p>
                        <p className="text-[11px] text-ink-400">
                          {formatDate(fulfillment.delivery_date)}
                          {fulfillment.tracking_number ? ` · ${fulfillment.tracking_number}` : ''}
                        </p>
                      </div>
                    </div>
                    <ExternalLink className="h-4 w-4 text-ink-400" />
                  </Link>
                ))}
              </div>
            ) : (
              <div className="px-5 py-8 text-center text-[13px] text-ink-400">
                No fulfillment logged for this payment.
              </div>
            )}
          </Card>

          {transaction.metadata && Object.keys(transaction.metadata).length ? (
            <Card>
              <CardHeader title="Paystack metadata" />
              <CardBody>
                <pre className="max-h-72 overflow-auto rounded-xl bg-navy p-4 text-[11px] leading-5 text-ink-100 scrollbar-thin">
                  {JSON.stringify(transaction.metadata, null, 2)}
                </pre>
              </CardBody>
            </Card>
          ) : null}
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader title="Customer" />
            <CardBody>
              {transaction.customer ? (
                <Link
                  href={`/customers/${transaction.customer.id}`}
                  className="group flex items-center gap-3"
                >
                  <Avatar name={transaction.customer.name ?? transaction.customer.email} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-semibold text-ink-900 group-hover:text-brand-700">
                      {transaction.customer.name ?? transaction.customer_name ?? 'Unnamed customer'}
                    </p>
                    <p className="truncate text-[11px] text-ink-400">
                      {transaction.customer.email ?? transaction.customer_email ?? 'No email'}
                    </p>
                  </div>
                  <ExternalLink className="h-4 w-4 text-ink-400" />
                </Link>
              ) : (
                <p className="text-[12px] text-ink-400">
                  {transaction.customer_email ?? 'No customer on this payment.'}
                </p>
              )}
            </CardBody>
          </Card>

          {transaction.dispute ? (
            <Card>
              <CardHeader title="Dispute" action={<Gavel className="h-4 w-4 text-danger" />} />
              <CardBody className="space-y-3 text-[13px]">
                <div className="flex items-center justify-between gap-2">
                  <Badge tone={statusTone(transaction.dispute.status)}>
                    {STATUS_LABELS[transaction.dispute.status]}
                  </Badge>
                  <span className="font-semibold text-ink-900">
                    {formatMoney(transaction.dispute.amount, transaction.dispute.currency)}
                  </span>
                </div>
                <Row label="Respond by" value={formatDateTime(transaction.dispute.due_at)} />
                <Link href={`/disputes/${transaction.dispute.id}`} className="block">
                  <Button variant="outline" className="w-full">
                    Open dispute
                  </Button>
                </Link>
              </CardBody>
            </Card>
          ) : null}

          <Card>
            <CardHeader
              title="Dispute readiness"
              description="How well this payment would defend itself today."
            />
            {transaction.readiness ? (
              <CardBody className="space-y-4">
                <div className="flex items-end justify-between">
                  <p className="text-[24px] font-semibold leading-none tracking-[-0.04em] text-ink-950">
                    {transaction.readiness.score}
                    <span className="text-base font-medium text-ink-400">/100</span>
                  </p>
                  <Badge
                    tone={
                      transaction.readiness.label === 'well_defended'
                        ? 'success'
                        : transaction.readiness.label === 'moderate'
                          ? 'warning'
                          : 'danger'
                    }
                  >
                    {titleCase(transaction.readiness.label)}
                  </Badge>
                </div>
                <Progress
                  value={transaction.readiness.score}
                  tone={
                    transaction.readiness.score >= 70
                      ? 'brand'
                      : transaction.readiness.score >= 40
                        ? 'amber'
                        : 'red'
                  }
                />
                <div className="space-y-2.5">
                  {transaction.readiness.components.map((component) => (
                    <div key={component.key} className="flex items-start gap-2.5 text-[12px]">
                      {component.status === 'available' ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
                      ) : (
                        <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="flex justify-between gap-2">
                          <span className="font-medium text-ink-800">{component.label}</span>
                          <span className="tabular-nums text-ink-400">
                            {component.points}/{component.max_points}
                          </span>
                        </div>
                        {component.suggestion ? (
                          <p className="mt-0.5 leading-5 text-ink-500">{component.suggestion}</p>
                        ) : null}
                      </div>
                    </div>
                  ))}
                </div>
              </CardBody>
            ) : (
              <CardBody>
                <p className="text-[12px] leading-5 text-ink-400">
                  Readiness is scored once the payment is matched to an order.
                </p>
              </CardBody>
            )}
          </Card>
        </div>
      </div>

      <Modal
        open={dialog === 'flag'}
        onClose={() => setDialog(null)}
        title="Flag this payment"
        description="Flagged payments are held out of automatic matching until you clear them."
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialog(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={!reason.trim()}
              loading={flagMutation.isPending}
              onClick={() => flagMutation.mutate(reason.trim())}
            >
              Flag payment
            </Button>
          </>
        }
      >
        <Label htmlFor="flag-reason">Reason</Label>
        <Textarea
          id="flag-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="e.g. Customer says they did not make this payment"
          maxLength={500}
        />
      </Modal>

      <MatchOrderModal
        open={dialog === 'match'}
        onClose={() => setDialog(null)}
        amount={transaction.amount}
        currency={transaction.currency}
        customerEmail={transaction.customer_email}
        loading={matchMutation.isPending}
        onMatch={(orderId) => matchMutation.mutate(orderId)}
      />
    </div>
  );
}

function MatchOrderModal({
  open,
  onClose,
  amount,
  currency,
  customerEmail,
  loading,
  onMatch,
}: {
  open: boolean;
  onClose: () => void;
  amount: number;
  currency: TransactionDetail['currency'];
  customerEmail: string | null;
  loading: boolean;
  onMatch: (orderId: string) => void;
}) {
  const [search, setSearch] = useState(customerEmail ?? '');
  const deferredSearch = useDeferredValue(search);
  const [selected, setSelected] = useState<string | null>(null);

  const ordersQuery = useQuery({
    queryKey: ['orders', 'match-candidates', deferredSearch],
    queryFn: () =>
      apiList<Order>(
        `/orders?limit=10&status=pending${deferredSearch ? `&search=${encodeURIComponent(deferredSearch)}` : ''}`,
      ),
    enabled: open,
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Match to an order"
      description={`Pick the pending order this ${formatMoney(amount, currency)} payment settles.`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!selected}
            loading={loading}
            onClick={() => selected && onMatch(selected)}
          >
            Match payment
          </Button>
        </>
      }
    >
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
        <Input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search order number, customer or description"
          className="pl-9"
        />
      </div>
      <FieldHint>Only pending orders without a payment can be matched.</FieldHint>
      <div className="mt-4 max-h-80 space-y-2 overflow-y-auto scrollbar-thin">
        {ordersQuery.isLoading ? (
          <p className="py-6 text-center text-[12px] text-ink-400">Loading orders…</p>
        ) : ordersQuery.data?.data.length ? (
          ordersQuery.data.data.map((order) => (
            <button
              key={order.id}
              type="button"
              onClick={() => setSelected(order.id)}
              className={cn(
                'flex w-full items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left transition',
                selected === order.id
                  ? 'border-brand-400 bg-brand-50 ring-1 ring-brand-300'
                  : 'border-line hover:bg-ink-50',
              )}
            >
              <div className="min-w-0">
                <p className="text-[13px] font-semibold text-ink-900">
                  Order {order.order_number ?? '—'}
                </p>
                <p className="truncate text-[11px] text-ink-400">
                  {order.customer?.email ?? order.description ?? 'No customer'} ·{' '}
                  {formatDate(order.created_at)}
                </p>
              </div>
              <div className="text-right">
                <p className="text-[13px] font-semibold text-ink-900">
                  {formatMoney(order.amount, order.currency)}
                </p>
                {order.amount === amount ? (
                  <p className="text-[10px] font-semibold text-brand-700">Same amount</p>
                ) : null}
              </div>
            </button>
          ))
        ) : (
          <p className="py-6 text-center text-[12px] text-ink-400">No pending orders found.</p>
        )}
      </div>
    </Modal>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-ink-500">{label}</span>
      <span className={cn('text-right font-medium text-ink-900', mono && 'font-mono text-[12px]')}>
        {value}
      </span>
    </div>
  );
}
