'use client';

import { useCallback, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useDropzone } from 'react-dropzone';
import { ArrowLeft, ExternalLink, ImagePlus, Pencil, X } from 'lucide-react';
import { toast } from 'sonner';
import { apiRequest, errorMessage, uploadFiles } from '@/lib/api';
import { formatDateTime, titleCase } from '@/lib/format';
import type { FileRef, Fulfillment, FulfillmentType, OrderDetail } from '@/lib/types';
import { FULFILLMENT_TYPES, ORDER_STATUS_LABELS } from '@/lib/constants';
import { cn } from '@/lib/cn';
import { PageSkeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import { Badge, statusTone } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Modal } from '@/components/ui/modal';
import { AuthImage } from '@/components/ui/auth-image';
import { Input, Label, Select, Textarea } from '@/components/ui/input';

function localDateTimeValue(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export default function FulfillmentDetailPage() {
  const params = useParams<{ id: string }>();
  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState<FileRef | null>(null);

  const fulfillmentQuery = useQuery({
    queryKey: ['fulfillments', 'detail', params.id],
    queryFn: () => apiRequest<Fulfillment>(`/fulfillments/${params.id}`),
    enabled: Boolean(params.id),
  });
  const orderId = fulfillmentQuery.data?.order_id;
  const orderQuery = useQuery({
    queryKey: ['order', orderId],
    queryFn: () => apiRequest<OrderDetail>(`/orders/${orderId}`),
    enabled: Boolean(orderId),
  });

  if (fulfillmentQuery.isLoading) return <PageSkeleton />;
  if (fulfillmentQuery.isError || !fulfillmentQuery.data) {
    return (
      <div className="space-y-5">
        <Link href="/fulfillments">
          <Button variant="outline">
            <ArrowLeft className="h-4 w-4" /> Back to fulfillments
          </Button>
        </Link>
        <Alert tone="danger" title="Could not load this fulfillment">
          {errorMessage(fulfillmentQuery.error)}
        </Alert>
      </div>
    );
  }

  const fulfillment = fulfillmentQuery.data;
  const order = orderQuery.data;
  const linkedPayment = order?.transactions.find((t) => t.id === fulfillment.transaction_id);

  return (
    <div className="space-y-6">
      <Link
        href="/fulfillments"
        className="inline-flex items-center gap-2 text-[12px] font-semibold text-ink-500 hover:text-ink-800"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> All fulfillments
      </Link>

      <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={fulfillment.files.length ? 'success' : 'warning'} dot>
              {fulfillment.files.length ? 'Photo evidence' : 'No photos yet'}
            </Badge>
            <Badge tone={fulfillment.transaction_id ? 'success' : 'neutral'}>
              {fulfillment.transaction_id ? 'Payment linked' : 'No payment linked'}
            </Badge>
          </div>
          <h1 className="mt-3 text-[24px] font-semibold tracking-[-0.04em] text-ink-950">
            {titleCase(fulfillment.type)}
          </h1>
          <p className="mt-1 text-sm text-ink-500">
            Delivered {formatDateTime(fulfillment.delivery_date)}
          </p>
        </div>
        <Button variant="outline" onClick={() => setEditing(true)}>
          <Pencil className="h-4 w-4" /> Edit
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.4fr_1fr]">
        <div className="space-y-6">
          <Card>
            <CardHeader title="Delivery details" />
            <CardBody className="space-y-3 text-[13px]">
              <Row label="Type" value={titleCase(fulfillment.type)} />
              <Row label="Delivered" value={formatDateTime(fulfillment.delivery_date)} />
              <Row label="Recipient" value={fulfillment.recipient_name ?? '—'} />
              <Row label="Tracking number" value={fulfillment.tracking_number ?? '—'} />
              <Row label="Address" value={fulfillment.delivery_address ?? '—'} />
              <Row label="Logged" value={formatDateTime(fulfillment.created_at)} />
              <Row label="Last edited" value={formatDateTime(fulfillment.updated_at)} />
              {fulfillment.notes ? (
                <div className="rounded-xl bg-ink-50/70 p-3 text-[12px] leading-5 text-ink-700">
                  {fulfillment.notes}
                </div>
              ) : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Photos"
              description="Shown to the card network in your dispute evidence."
            />
            {fulfillment.files.length ? (
              <div className="grid grid-cols-2 gap-3 p-5 sm:grid-cols-3">
                {fulfillment.files.map((file) => (
                  <AuthImage
                    key={file.id}
                    fileId={file.id}
                    alt={file.file_name}
                    className="h-36 w-full rounded-xl"
                    onClick={() => setPreview(file)}
                  />
                ))}
              </div>
            ) : (
              <div className="px-5 py-8 text-center text-[13px] text-ink-400">
                No photos attached. Edit this fulfillment to add some.
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader title="Order" />
            <CardBody className="space-y-3 text-[13px]">
              {order ? (
                <>
                  <div className="flex items-center justify-between gap-2">
                    <Link
                      href={`/orders/${order.id}`}
                      className="font-semibold text-ink-900 hover:text-brand-700"
                    >
                      Order {order.order_number ?? '—'}
                    </Link>
                    <Badge tone={statusTone(order.status)}>
                      {ORDER_STATUS_LABELS[order.status]}
                    </Badge>
                  </div>
                  <Row
                    label="Customer"
                    value={order.customer?.name ?? order.customer?.email ?? '—'}
                  />
                  {linkedPayment ? (
                    <Link
                      href={`/transactions/${encodeURIComponent(linkedPayment.reference)}`}
                      className="flex items-center justify-between rounded-xl border border-line px-3 py-2.5 text-[12px] hover:bg-ink-50"
                    >
                      <span className="font-mono text-ink-700">{linkedPayment.reference}</span>
                      <ExternalLink className="h-3.5 w-3.5 text-ink-400" />
                    </Link>
                  ) : null}
                </>
              ) : (
                <p className="text-[12px] text-ink-400">Loading order…</p>
              )}
            </CardBody>
          </Card>
          <Alert tone="info" title="Strong evidence">
            A dated photo of the delivered item and the recipient&apos;s name are what card networks
            weigh most in a &ldquo;not received&rdquo; dispute.
          </Alert>
        </div>
      </div>

      {editing ? (
        <EditFulfillmentModal fulfillment={fulfillment} onClose={() => setEditing(false)} />
      ) : null}

      <Modal
        open={preview !== null}
        onClose={() => setPreview(null)}
        title={preview?.file_name ?? 'Photo'}
        size="lg"
      >
        {preview ? (
          <AuthImage fileId={preview.id} alt={preview.file_name} className="max-h-[70vh] w-full" />
        ) : null}
      </Modal>
    </div>
  );
}

function EditFulfillmentModal({
  fulfillment,
  onClose,
}: {
  fulfillment: Fulfillment;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [type, setType] = useState<FulfillmentType>(fulfillment.type);
  const [deliveryDate, setDeliveryDate] = useState(localDateTimeValue(fulfillment.delivery_date));
  const [trackingNumber, setTrackingNumber] = useState(fulfillment.tracking_number ?? '');
  const [recipientName, setRecipientName] = useState(fulfillment.recipient_name ?? '');
  const [deliveryAddress, setDeliveryAddress] = useState(fulfillment.delivery_address ?? '');
  const [notes, setNotes] = useState(fulfillment.notes ?? '');
  const [files, setFiles] = useState<FileRef[]>(fulfillment.files);
  const [uploading, setUploading] = useState(false);

  const onDrop = useCallback(async (accepted: File[]) => {
    if (!accepted.length) return;
    setUploading(true);
    try {
      const uploaded = await uploadFiles(accepted);
      setFiles((current) => [...current, ...uploaded].slice(0, 10));
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setUploading(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'image/*': ['.jpg', '.jpeg', '.png', '.webp', '.heic'] },
    maxFiles: 10,
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<Fulfillment>(`/fulfillments/${fulfillment.id}`, {
        method: 'PATCH',
        body: {
          type,
          delivery_date: new Date(deliveryDate).toISOString(),
          tracking_number: trackingNumber || null,
          recipient_name: recipientName || null,
          delivery_address: deliveryAddress || null,
          notes: notes || null,
          file_ids: files.map((file) => file.id),
        },
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['fulfillments', 'detail', fulfillment.id], updated);
      queryClient.invalidateQueries({ queryKey: ['fulfillments', 'list'] });
      queryClient.invalidateQueries({ queryKey: ['order', fulfillment.order_id] });
      queryClient.invalidateQueries({ queryKey: ['disputes'] });
      toast.success('Fulfillment updated');
      onClose();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <Modal
      open
      onClose={onClose}
      title="Edit fulfillment"
      description="Changes flow into any open dispute's evidence."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => saveMutation.mutate()}
            loading={saveMutation.isPending}
            disabled={uploading}
          >
            Save changes
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <Label htmlFor="type">Type</Label>
          <Select
            id="type"
            value={type}
            onChange={(event) => setType(event.target.value as FulfillmentType)}
          >
            {FULFILLMENT_TYPES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="delivery-date">Delivered at</Label>
          <Input
            id="delivery-date"
            type="datetime-local"
            value={deliveryDate}
            onChange={(event) => setDeliveryDate(event.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="recipient">Recipient</Label>
          <Input
            id="recipient"
            value={recipientName}
            onChange={(event) => setRecipientName(event.target.value)}
            maxLength={255}
          />
        </div>
        <div>
          <Label htmlFor="tracking">Tracking number</Label>
          <Input
            id="tracking"
            value={trackingNumber}
            onChange={(event) => setTrackingNumber(event.target.value)}
            maxLength={255}
          />
        </div>
        <div className="sm:col-span-2">
          <Label htmlFor="address">Delivery address</Label>
          <Input
            id="address"
            value={deliveryAddress}
            onChange={(event) => setDeliveryAddress(event.target.value)}
            maxLength={2000}
          />
        </div>
        <div className="sm:col-span-2">
          <Label htmlFor="notes">Notes</Label>
          <Textarea
            id="notes"
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            maxLength={2000}
          />
        </div>
      </div>

      <div className="mt-5">
        <Label>Photos ({files.length}/10)</Label>
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
          {files.map((file) => (
            <div key={file.id} className="relative">
              <AuthImage fileId={file.id} alt={file.file_name} className="h-24 w-full rounded-xl" />
              <button
                type="button"
                onClick={() => setFiles((current) => current.filter((f) => f.id !== file.id))}
                className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-full bg-black/70 text-white hover:bg-navy"
                aria-label={`Remove ${file.file_name}`}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          {files.length < 10 ? (
            <div
              {...getRootProps()}
              className={cn(
                'flex h-24 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed text-[11px] font-semibold transition',
                isDragActive
                  ? 'border-brand-400 bg-brand-50 text-brand-700'
                  : 'border-line text-ink-500 hover:bg-ink-50',
              )}
            >
              <input {...getInputProps()} />
              {uploading ? (
                'Uploading…'
              ) : (
                <>
                  <ImagePlus className="mb-1 h-4 w-4" /> Add
                </>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </Modal>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-ink-500">{label}</span>
      <span className="text-right font-medium text-ink-900">{value}</span>
    </div>
  );
}
