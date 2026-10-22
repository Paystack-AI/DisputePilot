'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { apiRequest, errorMessage } from '@/lib/api';
import type { Customer } from '@/lib/types';
import { Modal } from '@/components/ui/modal';
import { Button } from '@/components/ui/button';
import { FieldHint, Input, Label } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';

export function CustomerEditModal({
  customer,
  onClose,
}: {
  customer: Customer;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(customer.name ?? '');
  const [email, setEmail] = useState(customer.email ?? '');
  const [phone, setPhone] = useState(customer.phone ?? '');
  const [isShared, setIsShared] = useState(customer.is_shared);

  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<Customer>(`/customers/${customer.id}`, {
        method: 'PATCH',
        body: {
          name: name.trim() || undefined,
          email: email.trim() || undefined,
          phone: phone.trim() || undefined,
          is_shared: isShared,
        },
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['customer', customer.id], updated);
      queryClient.invalidateQueries({ queryKey: ['customers'] });
      toast.success('Customer updated');
      onClose();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  return (
    <Modal
      open
      onClose={onClose}
      title="Edit customer"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
            Save changes
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <Label htmlFor="customer-name">Name</Label>
          <Input
            id="customer-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={255}
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="customer-email">Email</Label>
            <Input
              id="customer-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="customer-phone">Phone</Label>
            <Input
              id="customer-phone"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              placeholder="+2348031234567"
              maxLength={32}
            />
            <FieldHint>With the country code, e.g. +234 for Nigeria.</FieldHint>
          </div>
        </div>
        <div className="flex items-center justify-between gap-4 rounded-xl bg-ink-50/70 p-4">
          <div>
            <p className="text-[13px] font-semibold text-ink-900">Shared account</p>
            <FieldHint>
              One email used by several buyers (e.g. an office). Matching relies less on the email
              for shared accounts.
            </FieldHint>
          </div>
          <Switch checked={isShared} onChange={setIsShared} label="Shared account" />
        </div>
      </div>
    </Modal>
  );
}
