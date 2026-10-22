'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { ArrowLeft, Loader2, ShoppingBag } from 'lucide-react';
import { toast } from 'sonner';
import { apiRequest, errorMessage } from '@/lib/api';
import type { Order } from '@/lib/types';
import { CURRENCIES, ORDER_SOURCES } from '@/lib/constants';
import { PageHeader } from '@/components/ui/page-header';
import { Card, CardBody } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { FieldError, FieldHint, Input, Label, Select, Textarea } from '@/components/ui/input';
import { toLocalInput } from '@/lib/format';
import { Alert } from '@/components/ui/alert';

const schema = z.object({
  order_number: z.string().max(50).optional(),
  customer_email: z.string().email('Enter a valid customer email').optional().or(z.literal('')),
  description: z.string().max(2000).optional(),
  amount: z.coerce.number().positive('Amount must be greater than zero'),
  currency: z.enum(CURRENCIES),
  source: z.enum(['website', 'whatsapp', 'instagram', 'in_store', 'other']),
  ordered_at: z
    .string()
    .min(1, 'Enter when the order was placed')
    .refine((value) => new Date(value).getTime() <= Date.now() + 5 * 60_000, {
      message: 'The order date can not be in the future',
    }),
});

type FormValues = z.infer<typeof schema>;

function NewOrderForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [formError, setFormError] = useState<string | null>(null);
  const amountParam = searchParams.get('amount');
  const emailParam = searchParams.get('email') ?? '';
  const customerId = searchParams.get('customer');
  const reference = searchParams.get('reference');

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      order_number: '',
      customer_email: emailParam,
      description: reference ? `Payment reference ${reference}` : '',
      amount: amountParam ? Number(amountParam) / 100 : undefined,
      currency: 'NGN',
      source: 'website',
      ordered_at: toLocalInput(),
    },
  });

  const onSubmit = async (values: FormValues) => {
    setFormError(null);
    try {
      const order = await apiRequest<Order>('/orders', {
        method: 'POST',
        body: {
          order_number: values.order_number || undefined,
          customer_id: customerId || undefined,
          customer_email: !customerId && values.customer_email ? values.customer_email : undefined,
          description: values.description || undefined,
          amount: Math.round(values.amount * 100),
          currency: values.currency,
          source: values.source,
          ordered_at: new Date(values.ordered_at).toISOString(),
        },
      });
      toast.success('Order created');
      router.push(`/orders/${order.id}`);
    } catch (error) {
      setFormError(errorMessage(error));
    }
  };

  return (
    <div className="space-y-6">
      <Link
        href="/orders"
        className="inline-flex items-center gap-2 text-[12px] font-semibold text-ink-500 hover:text-ink-800"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> All orders
      </Link>
      <PageHeader
        eyebrow="New sale"
        title="Create an order"
        description="Log the sale now. When the Paystack payment arrives, reconciliation can match it automatically."
      />

      <div className="grid gap-6 xl:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardBody className="p-6">
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
              {formError ? <Alert tone="danger">{formError}</Alert> : null}
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="order_number">Order number</Label>
                  <Input id="order_number" placeholder="e.g. 1048" {...register('order_number')} />
                  <FieldError>{errors.order_number?.message}</FieldError>
                  <FieldHint>
                    Use the same reference in Paystack metadata for an exact match.
                  </FieldHint>
                </div>
                <div>
                  <Label htmlFor="customer_email">Customer email</Label>
                  <Input
                    id="customer_email"
                    type="email"
                    placeholder="customer@example.com"
                    {...register('customer_email')}
                  />
                  <FieldError>{errors.customer_email?.message}</FieldError>
                  {customerId ? (
                    <FieldHint>This order will use the selected customer.</FieldHint>
                  ) : null}
                </div>
              </div>

              <div>
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  rows={4}
                  placeholder="What did the customer buy?"
                  {...register('description')}
                />
                <FieldError>{errors.description?.message}</FieldError>
              </div>

              <div className="grid gap-4 sm:grid-cols-[1.2fr_0.8fr]">
                <div>
                  <Label htmlFor="amount">Amount</Label>
                  <Input
                    id="amount"
                    type="number"
                    min="0"
                    step="0.01"
                    placeholder="45000"
                    error={Boolean(errors.amount)}
                    {...register('amount')}
                  />
                  <FieldError>{errors.amount?.message}</FieldError>
                  <FieldHint>Enter the amount in major units, e.g. 45000 for ₦45,000.</FieldHint>
                </div>
                <div>
                  <Label htmlFor="currency">Currency</Label>
                  <Select id="currency" {...register('currency')}>
                    {CURRENCIES.map((currency) => (
                      <option key={currency} value={currency}>
                        {currency}
                      </option>
                    ))}
                  </Select>
                  <FieldError>{errors.currency?.message}</FieldError>
                </div>
              </div>

              <div>
                <Label htmlFor="source">Sales channel</Label>
                <Select id="source" {...register('source')}>
                  {ORDER_SOURCES.map((source) => (
                    <option key={source} value={source} className="capitalize">
                      {source.replace(/_/g, ' ')}
                    </option>
                  ))}
                </Select>
                <FieldError>{errors.source?.message}</FieldError>
              </div>

              <div>
                <Label htmlFor="ordered_at">Order placed</Label>
                <Input
                  id="ordered_at"
                  type="datetime-local"
                  max={toLocalInput()}
                  error={Boolean(errors.ordered_at)}
                  {...register('ordered_at')}
                />
                <FieldError>{errors.ordered_at?.message}</FieldError>
                <FieldHint>
                  Logging a sale after the fact? Set when it happened so it matches the right
                  payment.
                </FieldHint>
              </div>

              <div className="flex justify-end gap-2.5">
                <Link href="/orders">
                  <Button type="button" variant="outline">
                    Cancel
                  </Button>
                </Link>
                <Button type="submit" loading={isSubmitting}>
                  <ShoppingBag className="h-4 w-4" /> Create order
                </Button>
              </div>
            </form>
          </CardBody>
        </Card>

        <div className="space-y-4">
          <Card className="bg-ink-950 p-5 text-white">
            <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-brand-300">
              Make matching effortless
            </p>
            <h3 className="mt-3 text-xl font-semibold tracking-[-0.03em]">
              Put the order number in Paystack metadata.
            </h3>
            <p className="mt-2 text-[13px] leading-6 text-ink-300">
              The matcher looks for an exact order number in the payment reference or metadata
              first. That becomes a Tier 1 automatic match.
            </p>
            <div className="mt-4 rounded-xl bg-white/10 p-3 font-mono text-[11px] text-ink-200">
              metadata: {'{'} order_number: &quot;1048&quot; {'}'}
            </div>
          </Card>
          <Alert tone="info" title="Evidence starts here">
            Attach a customer and a clear description. If a dispute arrives, this becomes the
            backbone of the evidence narrative.
          </Alert>
        </div>
      </div>
    </div>
  );
}

export default function NewOrderPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-64 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
        </div>
      }
    >
      <NewOrderForm />
    </Suspense>
  );
}
