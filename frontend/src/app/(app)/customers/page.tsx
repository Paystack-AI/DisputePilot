'use client';

import { useDeferredValue, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { href, rowClick } from '@/lib/links';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Plus, Search, Users } from 'lucide-react';
import { toast } from 'sonner';
import { apiList, apiRequest, errorMessage } from '@/lib/api';
import { percent, timeAgo } from '@/lib/format';
import type { Customer, CustomerSummary, PageMeta } from '@/lib/types';
import { PageHeader } from '@/components/ui/page-header';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input, Label, FieldError } from '@/components/ui/input';
import { Avatar } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { EmptyState } from '@/components/ui/empty-state';
import { Modal } from '@/components/ui/modal';
import { Pagination } from '@/components/ui/pagination';
import { PageSkeleton } from '@/components/ui/skeleton';

export default function CustomersPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search);
  const [page, setPage] = useState(1);
  const [createOpen, setCreateOpen] = useState(false);
  const [form, setForm] = useState({ name: '', email: '', phone: '' });
  const [formError, setFormError] = useState<string | null>(null);

  const customersQuery = useQuery({
    queryKey: ['customers', deferredSearch, page],
    queryFn: () =>
      apiList<CustomerSummary>(
        `/customers?limit=20&page=${page}${deferredSearch ? `&search=${encodeURIComponent(deferredSearch)}` : ''}`,
      ),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      apiRequest<Customer>('/customers', {
        method: 'POST',
        body: {
          name: form.name || undefined,
          email: form.email || undefined,
          phone: form.phone || undefined,
        },
      }),
    onSuccess: (customer) => {
      toast.success('Customer added');
      setCreateOpen(false);
      setForm({ name: '', email: '', phone: '' });
      queryClient.invalidateQueries({ queryKey: ['customers'] });
      window.location.href = `/customers/${customer.id}`;
    },
    onError: (error) => setFormError(errorMessage(error)),
  });

  const meta: PageMeta | undefined = customersQuery.data?.meta;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Customer ledger"
        title="Customers"
        description="One profile per payer email. Payment history, reconciliation and disputes in context."
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" /> Add customer
          </Button>
        }
      />

      <Card className="p-4">
        <div className="relative max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" />
          <Input
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            placeholder="Search by name or email"
            className="pl-9"
          />
        </div>
      </Card>

      {customersQuery.isLoading ? (
        <PageSkeleton />
      ) : customersQuery.data?.data.length ? (
        <>
          <div className="table-shell overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Customer</th>
                  <th>Email</th>
                  <th>Payments</th>
                  <th>Reconciled</th>
                  <th>Disputes</th>
                  <th>Last payment</th>
                  <th>Shared</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {customersQuery.data.data.map((customer) => (
                  <tr
                    key={customer.id}
                    className="row-link"
                    onClick={rowClick(router.push, href.customer(customer.id))}
                  >
                    <td>
                      <Link
                        href={`/customers/${customer.id}`}
                        className="flex items-center gap-2.5"
                      >
                        <Avatar name={customer.name ?? customer.email} size="sm" />
                        <span className="font-medium text-ink-900">
                          {customer.name ?? 'Unnamed customer'}
                        </span>
                      </Link>
                    </td>
                    <td className="text-[12px] text-ink-500">{customer.email ?? '—'}</td>
                    <td className="font-semibold text-ink-900">{customer.payment_count}</td>
                    <td>
                      <span className="text-[12px] font-medium text-ink-700">
                        {percent(customer.reconciled_pct)}
                      </span>
                    </td>
                    <td>
                      {customer.dispute_count ? (
                        <Badge tone="danger">{customer.dispute_count}</Badge>
                      ) : (
                        <span className="text-[12px] text-ink-400">0</span>
                      )}
                    </td>
                    <td className="text-[12px] text-ink-500">
                      {customer.last_payment_at ? timeAgo(customer.last_payment_at) : '—'}
                    </td>
                    <td>
                      {customer.is_shared ? (
                        <Badge tone="info">Shared</Badge>
                      ) : (
                        <span className="text-[11px] text-ink-300">—</span>
                      )}
                    </td>
                    <td>
                      <Link href={`/customers/${customer.id}`}>
                        <Button variant="ghost" size="sm">
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
        </>
      ) : (
        <EmptyState
          icon={<Users className="h-5 w-5" />}
          title={deferredSearch ? 'No matching customers' : 'No customers yet'}
          description={
            deferredSearch
              ? 'Try a different name or email.'
              : 'Customers appear automatically when Paystack payments sync, or add one manually.'
          }
          action={
            deferredSearch ? null : (
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4" /> Add customer
              </Button>
            )
          }
        />
      )}

      <Modal
        open={createOpen}
        onClose={() => {
          setCreateOpen(false);
          setFormError(null);
        }}
        title="Add a customer"
        description="Useful for cash or offline customers. Email is the ledger identity."
        footer={
          <>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => createMutation.mutate()} loading={createMutation.isPending}>
              Add customer
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {formError ? <p className="text-[12px] font-medium text-danger">{formError}</p> : null}
          <div>
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="Customer name"
            />
          </div>
          <div>
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              value={form.email}
              onChange={(event) =>
                setForm((current) => ({ ...current, email: event.target.value }))
              }
              placeholder="customer@example.com"
            />
          </div>
          <div>
            <Label htmlFor="phone">Phone</Label>
            <Input
              id="phone"
              value={form.phone}
              onChange={(event) =>
                setForm((current) => ({ ...current, phone: event.target.value }))
              }
              placeholder="+2348031234567"
            />
            <FieldError>Include the country code for phone numbers.</FieldError>
          </div>
        </div>
      </Modal>
    </div>
  );
}
