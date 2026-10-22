'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { apiRequest, errorMessage } from '@/lib/api';
import type { Currency, Order, OrderSource } from '@/lib/types';
import { CURRENCIES, ORDER_SOURCES } from '@/lib/constants';
import { titleCase, toLocalInput } from '@/lib/format';
import { Modal } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import { FieldHint, Input, Label, Select, Textarea } from '@/components/ui/input';

export function OrderEditModal({ order, onClose }: { order: Order; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [orderNumber, setOrderNumber] = useState(order.order_number ?? '');
  const [description, setDescription] = useState(order.description ?? '');
  const [amount, setAmount] = useState(String(order.amount / 100));
  const [currency, setCurrency] = useState<Currency>(order.currency);
  const [source, setSource] = useState<OrderSource>(order.source);
  const [orderedAt, setOrderedAt] = useState(toLocalInput(order.ordered_at));
  // the amount and date are part of the match: once a payment is linked they can not change
  const amountLocked = order.is_linked;

  const minor = Math.round(Number(amount) * 100);
  const validAmount = Number.isFinite(minor) && minor > 0;
  const validDate = Boolean(orderedAt) && new Date(orderedAt).getTime() <= Date.now() + 5 * 60_000;

  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<Order>(`/orders/${order.id}`, {
        method: 'PATCH',
        body: {
          order_number: orderNumber.trim() || undefined,
          description: description.trim() || null,
          source,
          ...(amountLocked
            ? {}
            : { amount: minor, currency, ordered_at: new Date(orderedAt).toISOString() }),
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['order', order.id] });
      queryClient.invalidateQueries({ queryKey: ['orders'] });
      queryClient.invalidateQueries({ queryKey: ['reconciliation'] });
      toast.success('Order updated');
      onClose();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <Modal
      open
      onClose={onClose}
      title="Edit order"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={() => saveMutation.mutate()}
            loading={saveMutation.isPending}
            disabled={!validAmount || !validDate}
          >
            Save changes
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <Label htmlFor="order-number">Order number</Label>
          <Input
            id="order-number"
            value={orderNumber}
            onChange={(event) => setOrderNumber(event.target.value)}
            maxLength={50}
          />
        </div>
        <div>
          <Label htmlFor="source">Sales channel</Label>
          <Select
            id="source"
            value={source}
            onChange={(event) => setSource(event.target.value as OrderSource)}
          >
            {ORDER_SOURCES.map((value) => (
              <option key={value} value={value}>
                {titleCase(value)}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="amount">Amount</Label>
          <Input
            id="amount"
            type="number"
            min="0.01"
            step="0.01"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            disabled={amountLocked}
            error={!validAmount}
          />
        </div>
        <div>
          <Label htmlFor="currency">Currency</Label>
          <Select
            id="currency"
            value={currency}
            onChange={(event) => setCurrency(event.target.value as Currency)}
            disabled={amountLocked}
          >
            {CURRENCIES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Select>
        </div>
        <div className="sm:col-span-2">
          <Label htmlFor="ordered-at">Order placed</Label>
          <Input
            id="ordered-at"
            type="datetime-local"
            value={orderedAt}
            max={toLocalInput()}
            onChange={(event) => setOrderedAt(event.target.value)}
            disabled={amountLocked}
            error={!validDate}
          />
          <FieldHint>
            {amountLocked
              ? 'A payment is linked, so the amount, currency and date are fixed.'
              : 'When the sale happened. Reconciliation matches payments against this date.'}
          </FieldHint>
        </div>
        <div className="sm:col-span-2">
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            maxLength={2000}
          />
        </div>
      </div>
    </Modal>
  );
}
