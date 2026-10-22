'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Camera,
  CheckCircle2,
  CircleSlash2,
  ExternalLink,
  Flag,
  Pencil,
  PackageCheck,
  ReceiptText,
  Truck,
  UserRound,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiRequest, errorMessage } from '@/lib/api';
import { formatDate, formatDateTime, formatMoney, timeAgo, titleCase } from '@/lib/format';
import type { OrderDetail } from '@/lib/types';
import { ORDER_STATUS_LABELS, RECONCILIATION_LABELS } from '@/lib/constants';
import { PageSkeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import { Badge, statusTone } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Avatar } from '@/components/ui/avatar';
import { Modal } from '@/components/ui/modal';
import { Label, Textarea } from '@/components/ui/input';
import { OrderEditModal } from '@/components/orders/order-edit-modal';

export default function OrderDetailPage() {
  const params = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState<'cash' | 'failed' | 'cancel' | null>(null);
  const [editing, setEditing] = useState(false);
  const [flagging, setFlagging] = useState(false);
  const [flagReason, setFlagReason] = useState('');

  const orderQuery = useQuery({
    queryKey: ['order', params.id],
    queryFn: () => apiRequest<OrderDetail>(`/orders/${params.id}`),
    enabled: Boolean(params.id),
  });

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['order', params.id] });
    queryClient.invalidateQueries({ queryKey: ['orders'] });
    queryClient.invalidateQueries({ queryKey: ['dashboard'] });
  };

  const resolveMutation = useMutation({
    mutationFn: (resolution: 'cash_payment' | 'payment_failed') =>
      apiRequest(`/orders/${params.id}/resolve`, {
        method: 'PUT',
        body: { resolution },
      }),
    onSuccess: () => {
      toast.success('Order updated');
      setConfirm(null);
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const cancelMutation = useMutation({
    mutationFn: () => apiRequest(`/orders/${params.id}`, { method: 'DELETE' }),
    onSuccess: () => {
      toast.success('Order cancelled');
      setConfirm(null);
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const flagMutation = useMutation({
    mutationFn: (reason: string) =>
      apiRequest(`/orders/${params.id}/flag`, { method: 'PUT', body: { reason } }),
    onSuccess: () => {
      toast.success('Order flagged for review');
      setFlagging(false);
      setFlagReason('');
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const unflagMutation = useMutation({
    mutationFn: () => apiRequest(`/orders/${params.id}/unflag`, { method: 'PUT' }),
    onSuccess: () => {
      toast.success('Flag removed');
      refresh();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (orderQuery.isLoading) return <PageSkeleton />;
  if (orderQuery.isError || !orderQuery.data) {
    return (
      <div className="space-y-5">
        <Link href="/orders">
          <Button variant="outline">
            <ArrowLeft className="h-4 w-4" /> Back to orders
          </Button>
        </Link>
        <Alert tone="danger" title="Could not load this order">
          {errorMessage(orderQuery.error)}
        </Alert>
      </div>
    );
  }

  const order = orderQuery.data;
  const canResolve = order.status === 'pending' && !order.is_linked;

  return (
    <div className="space-y-6">
      <Link
        href="/orders"
        className="inline-flex items-center gap-2 text-[12px] font-semibold text-ink-500 hover:text-ink-800"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> All orders
      </Link>

      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={statusTone(order.status)}>{ORDER_STATUS_LABELS[order.status]}</Badge>
            <Badge tone={order.is_linked ? 'success' : 'neutral'}>
              {order.is_linked ? 'Payment linked' : 'No payment yet'}
            </Badge>
            {order.resolution ? <Badge tone="info">{titleCase(order.resolution)}</Badge> : null}
          </div>
          <h1 className="mt-3 text-[24px] font-semibold tracking-[-0.04em] text-ink-950">
            Order {order.order_number ?? '—'}
          </h1>
          <p className="mt-1 text-sm text-ink-500">
            {formatMoney(order.amount, order.currency)} · {titleCase(order.source)} · placed{' '}
            {timeAgo(order.ordered_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          {order.status !== 'cancelled' ? (
            <Button variant="outline" onClick={() => setEditing(true)}>
              <Pencil className="h-4 w-4" /> Edit
            </Button>
          ) : null}
          {order.flag_reason ? (
            <Button
              variant="outline"
              onClick={() => unflagMutation.mutate()}
              loading={unflagMutation.isPending}
            >
              Remove flag
            </Button>
          ) : order.status !== 'cancelled' ? (
            <Button variant="ghost" onClick={() => setFlagging(true)}>
              <Flag className="h-4 w-4" /> Flag
            </Button>
          ) : null}
          {order.status === 'paid' || order.status === 'fulfilled' ? (
            <Link href={`/fulfillments/new?order=${order.id}`}>
              <Button>
                <Camera className="h-4 w-4" /> Log fulfillment
              </Button>
            </Link>
          ) : null}
          {canResolve ? (
            <>
              <Button variant="outline" onClick={() => setConfirm('cash')}>
                Mark as cash
              </Button>
              <Button variant="ghost" onClick={() => setConfirm('failed')}>
                Payment failed
              </Button>
            </>
          ) : null}
          {order.status === 'pending' ? (
            <Button variant="danger" onClick={() => setConfirm('cancel')}>
              Cancel order
            </Button>
          ) : null}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.4fr_1fr]">
        <div className="space-y-6">
          <Card>
            <CardHeader title="Order details" />
            <CardBody className="space-y-3 text-[13px]">
              <Row label="Description" value={order.description ?? 'No description'} />
              <Row label="Amount" value={formatMoney(order.amount, order.currency)} />
              <Row label="Sales channel" value={titleCase(order.source)} />
              <Row label="Placed" value={formatDateTime(order.ordered_at)} />
              <Row label="Logged" value={formatDateTime(order.created_at)} />
              <Row label="Last updated" value={formatDateTime(order.updated_at)} />
              {order.flag_reason ? (
                <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-[12px] text-red-800">
                  <p className="font-semibold">Flagged for review</p>
                  <p className="mt-1">{order.flag_reason}</p>
                </div>
              ) : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Linked payments"
              description="Paystack transactions settled against this order."
            />
            {order.transactions.length ? (
              <div className="overflow-x-auto">
                <table className="table-base">
                  <thead>
                    <tr>
                      <th>Reference</th>
                      <th>Amount</th>
                      <th>Status</th>
                      <th>Reconciliation</th>
                      <th>Paid</th>
                    </tr>
                  </thead>
                  <tbody>
                    {order.transactions.map((transaction) => (
                      <tr key={transaction.id}>
                        <td className="font-mono text-[12px] font-semibold text-ink-900">
                          <Link
                            href={`/transactions/${encodeURIComponent(transaction.reference)}`}
                            className="hover:text-brand-700"
                          >
                            {transaction.reference}
                          </Link>
                        </td>
                        <td className="font-semibold text-ink-900">
                          {formatMoney(transaction.amount, transaction.currency)}
                        </td>
                        <td>
                          <Badge tone={statusTone(transaction.status)}>{transaction.status}</Badge>
                        </td>
                        <td className="text-[12px] text-ink-500">
                          {RECONCILIATION_LABELS[transaction.reconciliation_status]}
                        </td>
                        <td className="text-[12px] text-ink-500">
                          {transaction.paid_at ? formatDateTime(transaction.paid_at) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="px-5 py-8 text-center text-[13px] text-ink-400">
                No payment has been matched to this order yet.
              </div>
            )}
          </Card>

          <Card>
            <CardHeader
              title="Fulfillment evidence"
              description="Proof captured against this order."
              action={
                <Link href={`/fulfillments/new?order=${order.id}`}>
                  <Button variant="outline" size="sm">
                    <Camera className="h-3.5 w-3.5" /> Add
                  </Button>
                </Link>
              }
            />
            {order.fulfillments.length ? (
              <div className="space-y-3 p-5">
                {order.fulfillments.map((fulfillment) => (
                  <Link
                    key={fulfillment.id}
                    href={`/fulfillments/${fulfillment.id}`}
                    className="block rounded-xl border border-line p-4 transition hover:bg-ink-50/60"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
                          <Truck className="h-4 w-4" />
                        </div>
                        <div>
                          <p className="text-[13px] font-semibold text-ink-900">
                            {titleCase(fulfillment.type)}
                          </p>
                          <p className="text-[11px] text-ink-400">
                            {formatDate(fulfillment.delivery_date)}
                          </p>
                        </div>
                      </div>
                      <Badge tone="success" dot>
                        Evidence logged
                      </Badge>
                    </div>
                    <div className="mt-3 grid gap-2 text-[12px] sm:grid-cols-2">
                      <Row label="Recipient" value={fulfillment.recipient_name ?? '—'} compact />
                      <Row label="Tracking" value={fulfillment.tracking_number ?? '—'} compact />
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center px-5 py-10 text-center">
                <PackageCheck className="h-6 w-6 text-ink-300" />
                <p className="mt-3 text-[13px] font-semibold text-ink-700">
                  No fulfillment evidence yet
                </p>
                <p className="mt-1 max-w-sm text-[12px] leading-5 text-ink-400">
                  Delivery photos and tracking are the strongest evidence if this order is disputed.
                </p>
                <Link href={`/fulfillments/new?order=${order.id}`} className="mt-4">
                  <Button variant="outline" size="sm">
                    <Camera className="h-3.5 w-3.5" /> Log fulfillment
                  </Button>
                </Link>
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader title="Customer" />
            <CardBody>
              {order.customer ? (
                <Link
                  href={`/customers/${order.customer.id}`}
                  className="group flex items-center gap-3"
                >
                  <Avatar name={order.customer.name ?? order.customer.email} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-semibold text-ink-900 group-hover:text-brand-700">
                      {order.customer.name ?? 'Unnamed customer'}
                    </p>
                    <p className="truncate text-[11px] text-ink-400">
                      {order.customer.email ?? 'No email'}
                    </p>
                  </div>
                  <ExternalLink className="h-4 w-4 text-ink-400" />
                </Link>
              ) : (
                <p className="text-[12px] text-ink-400">No customer attached to this order.</p>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Evidence snapshot" />
            <CardBody className="space-y-3">
              <EvidenceRow icon={<ReceiptText className="h-4 w-4" />} label="Order record" done />
              <EvidenceRow
                icon={<CheckCircle2 className="h-4 w-4" />}
                label="Linked payment"
                done={order.is_linked}
              />
              <EvidenceRow
                icon={<Truck className="h-4 w-4" />}
                label="Fulfillment proof"
                done={order.fulfillments.length > 0}
              />
              <EvidenceRow
                icon={<UserRound className="h-4 w-4" />}
                label="Customer history"
                done={Boolean(order.customer)}
              />
            </CardBody>
          </Card>

          <Alert tone="info" title="Why this matters">
            This order, its payment and its fulfillment become a single evidence bundle if a
            chargeback arrives. Missing pieces are surfaced before the deadline.
          </Alert>
        </div>
      </div>

      <Modal
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        title={
          confirm === 'cash'
            ? 'Mark this order as paid in cash?'
            : confirm === 'failed'
              ? 'Mark this payment as failed?'
              : 'Cancel this order?'
        }
        description={
          confirm === 'cash'
            ? 'The order becomes paid even though no Paystack payment is linked.'
            : confirm === 'failed'
              ? 'The order becomes cancelled because it was never paid.'
              : 'The order is soft-deleted and removed from matching.'
        }
        footer={
          <>
            <Button variant="outline" onClick={() => setConfirm(null)}>
              Keep order
            </Button>
            <Button
              variant={confirm === 'cash' ? 'primary' : 'danger'}
              loading={resolveMutation.isPending || cancelMutation.isPending}
              onClick={() => {
                if (confirm === 'cash') resolveMutation.mutate('cash_payment');
                else if (confirm === 'failed') resolveMutation.mutate('payment_failed');
                else cancelMutation.mutate();
              }}
            >
              {confirm === 'cash'
                ? 'Mark as cash'
                : confirm === 'failed'
                  ? 'Mark failed'
                  : 'Cancel order'}
            </Button>
          </>
        }
      >
        <div className="flex items-center gap-3 rounded-xl bg-ink-50 p-4 text-[12px] text-ink-600">
          {confirm === 'cash' ? (
            <CircleSlash2 className="h-5 w-5 text-ink-400" />
          ) : (
            <PackageCheck className="h-5 w-5 text-ink-400" />
          )}
          Order {order.order_number ?? '—'} · {formatMoney(order.amount, order.currency)}
        </div>
      </Modal>

      {editing ? <OrderEditModal order={order} onClose={() => setEditing(false)} /> : null}

      <Modal
        open={flagging}
        onClose={() => setFlagging(false)}
        title="Flag this order"
        description="Flagged orders are held out of automatic matching until you clear them."
        size="sm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setFlagging(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              disabled={!flagReason.trim()}
              loading={flagMutation.isPending}
              onClick={() => flagMutation.mutate(flagReason.trim())}
            >
              Flag order
            </Button>
          </>
        }
      >
        <Label htmlFor="order-flag-reason">Reason</Label>
        <Textarea
          id="order-flag-reason"
          value={flagReason}
          onChange={(event) => setFlagReason(event.target.value)}
          placeholder="e.g. Customer asked to hold this order"
          maxLength={500}
        />
      </Modal>
    </div>
  );
}

function Row({
  label,
  value,
  compact,
}: {
  label: string;
  value: React.ReactNode;
  compact?: boolean;
}) {
  return (
    <div
      className={
        compact
          ? 'flex items-center justify-between gap-3'
          : 'flex items-start justify-between gap-4'
      }
    >
      <span className={compact ? 'text-ink-400' : 'text-ink-500'}>{label}</span>
      <span className="max-w-[65%] text-right font-medium text-ink-800">{value}</span>
    </div>
  );
}

function EvidenceRow({
  icon,
  label,
  done,
}: {
  icon: React.ReactNode;
  label: string;
  done: boolean;
}) {
  return (
    <div className="flex items-center gap-3">
      <div
        className={
          done
            ? 'flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-700'
            : 'flex h-8 w-8 items-center justify-center rounded-lg bg-ink-100 text-ink-400'
        }
      >
        {icon}
      </div>
      <p className="flex-1 text-[12px] font-medium text-ink-700">{label}</p>
      <Badge tone={done ? 'success' : 'neutral'}>{done ? 'Available' : 'Missing'}</Badge>
    </div>
  );
}
