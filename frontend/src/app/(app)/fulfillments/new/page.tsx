'use client';

import { Suspense, useCallback, useDeferredValue, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { useDropzone } from 'react-dropzone';
import {
  ArrowLeft,
  Camera,
  CheckCircle2,
  ImagePlus,
  Loader2,
  PackageCheck,
  Search,
  ShieldCheck,
  Trash2,
  Truck,
  X,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiList, apiRequest, deleteUpload, errorMessage, uploadFiles } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatMoney, titleCase } from '@/lib/format';
import type { FileRef, Fulfillment, Order, OrderDetail } from '@/lib/types';
import { FULFILLMENT_TYPES } from '@/lib/constants';
import { PageHeader } from '@/components/ui/page-header';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { FieldHint, Input, Label, Select, Textarea } from '@/components/ui/input';
import { Alert } from '@/components/ui/alert';
import { AuthImage } from '@/components/ui/auth-image';
import { Badge } from '@/components/ui/badge';

function localDateTimeValue(date: Date) {
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60_000).toISOString().slice(0, 16);
}

function FulfillmentForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const orderParam = searchParams.get('order');
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search);
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null);
  const [type, setType] = useState('delivery');
  const [deliveryDate, setDeliveryDate] = useState(localDateTimeValue(new Date()));
  const [trackingNumber, setTrackingNumber] = useState('');
  const [recipientName, setRecipientName] = useState('');
  const [deliveryAddress, setDeliveryAddress] = useState('');
  const [notes, setNotes] = useState('');
  const [files, setFiles] = useState<FileRef[]>([]);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [idempotencyKey] = useState(() =>
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random()}`,
  );

  const orderQuery = useQuery({
    queryKey: ['order', orderParam],
    queryFn: () => apiRequest<OrderDetail>(`/orders/${orderParam}`),
    enabled: Boolean(orderParam),
  });

  useEffect(() => {
    if (orderQuery.data && !selectedOrder) setSelectedOrder(orderQuery.data);
  }, [orderQuery.data, selectedOrder]);

  const ordersQuery = useQuery({
    queryKey: ['orders', 'fulfillment-search', deferredSearch],
    queryFn: () =>
      apiList<Order>(
        `/orders?limit=8${deferredSearch ? `&search=${encodeURIComponent(deferredSearch)}` : ''}`,
      ),
    enabled: !selectedOrder,
  });

  const onDrop = useCallback(async (accepted: File[]) => {
    if (!accepted.length) return;
    setUploading(true);
    try {
      const uploaded = await uploadFiles(accepted);
      setFiles((current) => [...current, ...uploaded]);
      toast.success(`${uploaded.length} photo${uploaded.length === 1 ? '' : 's'} attached`);
    } catch (uploadError) {
      toast.error(errorMessage(uploadError));
    } finally {
      setUploading(false);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'image/*': ['.jpg', '.jpeg', '.png', '.webp', '.heic'] },
    maxFiles: 8,
  });

  const removeFile = (fileId: string) => {
    setFiles((current) => current.filter((item) => item.id !== fileId));
    // Best effort: the upload is still cleaned up after a day if this fails.
    void deleteUpload(fileId).catch(() => undefined);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedOrder) {
      setError('Choose the order this fulfillment belongs to.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const fulfillment = await apiRequest<Fulfillment>('/fulfillments', {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey },
        body: {
          order_id: selectedOrder.id,
          type,
          delivery_date: new Date(deliveryDate).toISOString(),
          tracking_number: trackingNumber || undefined,
          recipient_name: recipientName || undefined,
          delivery_address: deliveryAddress || undefined,
          notes: notes || undefined,
          file_ids: files.length ? files.map((file) => file.id) : undefined,
        },
      });
      toast.success('Fulfillment logged');
      router.push(`/orders/${fulfillment.order_id}`);
    } catch (submitError) {
      setError(errorMessage(submitError));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <Link
        href={selectedOrder ? `/orders/${selectedOrder.id}` : '/orders'}
        className="inline-flex items-center gap-2 text-[12px] font-semibold text-ink-500 hover:text-ink-800"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> {selectedOrder ? 'Back to order' : 'All orders'}
      </Link>

      <PageHeader
        eyebrow="Evidence collection"
        title="Log a fulfillment"
        description="Capture proof immediately after handoff. It should take less than a minute."
        actions={
          <div className="flex items-center gap-2 rounded-xl bg-brand-50 px-3 py-2 text-[11px] font-semibold text-brand-700 ring-1 ring-inset ring-brand-200">
            <ShieldCheck className="h-3.5 w-3.5" /> Counts towards your trust profile
          </div>
        }
      />

      <form onSubmit={submit} className="grid grid-cols-1 gap-6 xl:grid-cols-[1.35fr_1fr]">
        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Which order?"
              description="Search by order number, customer or amount."
            />
            <CardBody>
              {selectedOrder ? (
                <div className="flex items-center justify-between gap-3 rounded-xl border border-brand-200 bg-brand-50/60 p-3.5">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-500 text-white">
                      <PackageCheck className="h-4 w-4" />
                    </div>
                    <div>
                      <p className="text-[13px] font-semibold text-ink-900">
                        Order {selectedOrder.order_number ?? '—'}
                      </p>
                      <p className="text-[11px] text-ink-500">
                        {selectedOrder.customer?.name ??
                          selectedOrder.customer?.email ??
                          'No customer'}{' '}
                        · {formatMoney(selectedOrder.amount, selectedOrder.currency)}
                      </p>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => setSelectedOrder(null)}
                    aria-label="Change order"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ) : (
                <div>
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
                    <Input
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="Search orders"
                      className="pl-9"
                    />
                  </div>
                  {ordersQuery.isLoading ? (
                    <div className="flex h-20 items-center justify-center">
                      <Loader2 className="h-4 w-4 animate-spin text-brand-600" />
                    </div>
                  ) : ordersQuery.data?.data.length ? (
                    <div className="mt-2 max-h-64 space-y-1.5 overflow-y-auto scrollbar-thin">
                      {ordersQuery.data.data.map((order) => (
                        <button
                          key={order.id}
                          type="button"
                          onClick={() => setSelectedOrder(order)}
                          className="flex w-full items-center justify-between gap-3 rounded-xl border border-line px-3.5 py-3 text-left transition hover:border-brand-300 hover:bg-brand-50/50"
                        >
                          <div className="min-w-0">
                            <p className="text-[12px] font-semibold text-ink-900">
                              Order {order.order_number ?? '—'}
                            </p>
                            <p className="mt-0.5 truncate text-[11px] text-ink-500">
                              {order.customer?.name ?? order.customer?.email ?? 'No customer'} ·{' '}
                              {titleCase(order.status)}
                            </p>
                          </div>
                          <span className="shrink-0 text-[12px] font-semibold text-ink-900">
                            {formatMoney(order.amount, order.currency)}
                          </span>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-4 text-center text-[12px] text-ink-400">
                      No orders found. Create one first.
                    </p>
                  )}
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Fulfillment details" />
            <CardBody className="space-y-4">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="type">Fulfillment type</Label>
                  <Select id="type" value={type} onChange={(event) => setType(event.target.value)}>
                    {FULFILLMENT_TYPES.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </Select>
                </div>
                <div>
                  <Label htmlFor="date">Delivery / completion date</Label>
                  <Input
                    id="date"
                    type="datetime-local"
                    value={deliveryDate}
                    onChange={(event) => setDeliveryDate(event.target.value)}
                  />
                </div>
              </div>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="recipient">Recipient name</Label>
                  <Input
                    id="recipient"
                    value={recipientName}
                    onChange={(event) => setRecipientName(event.target.value)}
                    placeholder="Who received it?"
                  />
                </div>
                <div>
                  <Label htmlFor="tracking">Tracking number</Label>
                  <Input
                    id="tracking"
                    value={trackingNumber}
                    onChange={(event) => setTrackingNumber(event.target.value)}
                    placeholder="Courier tracking reference"
                  />
                </div>
              </div>
              <div>
                <Label htmlFor="address">Delivery address</Label>
                <Input
                  id="address"
                  value={deliveryAddress}
                  onChange={(event) => setDeliveryAddress(event.target.value)}
                  placeholder="Where was it delivered?"
                />
              </div>
              <div>
                <Label htmlFor="notes">Notes</Label>
                <Textarea
                  id="notes"
                  rows={3}
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  placeholder="e.g. Delivered to customer at Ikeja office, 3:14 PM."
                />
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Photo proof"
              description="The single most valuable evidence item. Multiple photos are welcome."
              action={
                <Badge tone={files.length ? 'success' : 'neutral'}>{files.length} attached</Badge>
              }
            />
            <CardBody>
              {files.length ? (
                <div className="mb-3 grid grid-cols-2 gap-2.5 sm:grid-cols-3">
                  {files.map((file) => (
                    <div
                      key={file.id}
                      className="group relative overflow-hidden rounded-xl border border-line"
                    >
                      <AuthImage fileId={file.id} alt={file.file_name} className="h-28 w-full" />
                      <button
                        type="button"
                        className="absolute right-1.5 top-1.5 flex h-7 w-7 items-center justify-center rounded-lg bg-surface/90 text-danger opacity-0 shadow transition group-hover:opacity-100"
                        onClick={() => removeFile(file.id)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}
              <div
                {...getRootProps()}
                className={cn(
                  'flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-4 py-8 text-center transition',
                  isDragActive
                    ? 'border-brand-400 bg-brand-50'
                    : 'border-line bg-ink-50/40 hover:border-brand-300 hover:bg-brand-50/30',
                )}
              >
                <input {...getInputProps()} />
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-surface text-brand-700 shadow-sm ring-1 ring-inset ring-line">
                  {uploading ? (
                    <Loader2 className="h-5 w-5 animate-spin" />
                  ) : (
                    <ImagePlus className="h-5 w-5" />
                  )}
                </div>
                <p className="mt-3 text-[13px] font-semibold text-ink-800">
                  {uploading ? 'Uploading photos' : 'Drop photos or take a picture'}
                </p>
                <p className="mt-1 text-[11px] text-ink-400">
                  JPEG, PNG, WebP or HEIC · up to 8 photos
                </p>
              </div>
              <FieldHint>
                Images are stripped of metadata and stored securely. They are only visible to you.
              </FieldHint>
            </CardBody>
          </Card>
        </div>

        <div className="space-y-6">
          <Card className="bg-navy p-5 text-white">
            <div className="flex items-center gap-2 text-brand-300">
              <Camera className="h-4 w-4" />
              <p className="text-[11px] font-semibold uppercase tracking-[0.06em]">Quick log</p>
            </div>
            <h3 className="mt-3 text-xl font-semibold tracking-[-0.03em]">
              Select order, snap a photo, save.
            </h3>
            <p className="mt-2 text-[12px] leading-6 text-ink-300">
              Every fulfillment you log becomes ready-to-use evidence. Merchants who log daily win
              more disputes because the proof is already there.
            </p>
            <div className="mt-4 space-y-2">
              {[
                'Choose the paid order',
                'Add a delivery photo',
                'Save — order becomes fulfilled',
              ].map((step, index) => (
                <div key={step} className="flex items-center gap-2.5 text-[12px] text-ink-200">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white/10 text-[10px] font-bold text-brand-300">
                    {index + 1}
                  </span>
                  {step}
                </div>
              ))}
            </div>
          </Card>

          {selectedOrder ? (
            <Card>
              <CardHeader title="Order summary" />
              <CardBody className="space-y-2.5 text-[12px]">
                <SummaryRow label="Order" value={selectedOrder.order_number ?? '—'} />
                <SummaryRow
                  label="Customer"
                  value={selectedOrder.customer?.name ?? selectedOrder.customer?.email ?? '—'}
                />
                <SummaryRow
                  label="Amount"
                  value={formatMoney(selectedOrder.amount, selectedOrder.currency)}
                />
                <SummaryRow label="Status" value={titleCase(selectedOrder.status)} />
                <SummaryRow label="Photos" value={`${files.length} attached`} />
              </CardBody>
            </Card>
          ) : null}

          {error ? <Alert tone="danger">{error}</Alert> : null}

          <Card>
            <CardBody className="space-y-3">
              <div className="flex items-center gap-2 rounded-xl bg-brand-50 px-3.5 py-3 text-[12px] text-brand-800">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-brand-600" />A paid order becomes
                fulfilled automatically when you save.
              </div>
              <Button
                type="submit"
                size="lg"
                className="w-full"
                loading={submitting}
                disabled={!selectedOrder || uploading}
              >
                <Truck className="h-4 w-4" /> Save fulfillment
              </Button>
              <Link href={selectedOrder ? `/orders/${selectedOrder.id}` : '/orders'}>
                <Button type="button" variant="ghost" className="w-full">
                  Cancel
                </Button>
              </Link>
            </CardBody>
          </Card>
        </div>
      </form>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-ink-500">{label}</span>
      <span className="font-medium text-ink-800">{value}</span>
    </div>
  );
}

export default function FulfillmentPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
        </div>
      }
    >
      <FulfillmentForm />
    </Suspense>
  );
}
