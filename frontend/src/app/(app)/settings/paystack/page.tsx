'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  CheckCircle2,
  CreditCard,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Lock,
  RefreshCcw,
  ShieldCheck,
  TriangleAlert,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiRequest, errorMessage } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDate, formatDateTime, titleCase } from '@/lib/format';
import type { PaystackConnection } from '@/lib/types';
import { PageHeader } from '@/components/ui/page-header';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Alert } from '@/components/ui/alert';

const KEY_PATTERN = /^sk_(test|live)_[A-Za-z0-9]+$/;

export default function PaystackSettingsPage() {
  const queryClient = useQueryClient();
  const [secretKey, setSecretKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [replaceMode, setReplaceMode] = useState(false);
  const [showReplaceConfirm, setShowReplaceConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const statusQuery = useQuery({
    queryKey: ['paystack', 'status'],
    queryFn: () => apiRequest<PaystackConnection>('/auth/paystack/status'),
  });

  const connectMutation = useMutation({
    mutationFn: (key: string) =>
      apiRequest<PaystackConnection>('/auth/paystack/connect', {
        method: 'POST',
        body: { secret_key: key },
      }),
    onSuccess: (connection) => {
      queryClient.setQueryData(['paystack', 'status'], connection);
      queryClient.invalidateQueries({ queryKey: ['merchant'] });
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      queryClient.invalidateQueries({ queryKey: ['onboarding'] });
      setSecretKey('');
      setShowKey(false);
      setReplaceMode(false);
      setShowReplaceConfirm(false);
      setError(null);
      toast.success(
        connection.mode === 'test' ? 'Paystack test account connected' : 'Paystack connected',
      );
    },
    onError: (mutationError) => setError(errorMessage(mutationError)),
  });

  const status = statusQuery.data;
  const showForm = !status?.connected || replaceMode;
  const mode = secretKey.startsWith('sk_live_')
    ? 'live'
    : secretKey.startsWith('sk_test_')
      ? 'test'
      : null;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!KEY_PATTERN.test(secretKey.trim())) {
      setError('Enter a valid Paystack secret key. It starts with sk_test_ or sk_live_.');
      return;
    }
    connectMutation.mutate(secretKey.trim());
  };

  if (statusQuery.isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link
        href="/settings"
        className="inline-flex items-center gap-2 text-[12px] font-semibold text-ink-500 hover:text-ink-800"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Settings
      </Link>

      <PageHeader
        eyebrow="Payment source"
        title="Paystack connection"
        description="DisputePilot needs read access to your transactions so reconciliation and disputes are grounded in real payments."
        actions={
          status?.connected ? (
            <Badge tone="success">
              <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-brand-600" /> Connected
            </Badge>
          ) : (
            <Badge tone="neutral">Not connected</Badge>
          )
        }
      />

      {statusQuery.isError ? (
        <Alert tone="danger" title="Could not check connection status">
          {errorMessage(statusQuery.error)}
        </Alert>
      ) : null}

      {status?.connected ? (
        <Card>
          <CardHeader
            title="Connection details"
            description="Your key is encrypted at rest and never shown again."
            action={<ShieldCheck className="h-4 w-4 text-brand-600" />}
          />
          <CardBody className="space-y-4">
            <div className="flex items-center gap-3 rounded-xl border border-brand-200 bg-brand-50/60 p-4">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-white">
                <CheckCircle2 className="h-5 w-5" />
              </div>
              <div>
                <p className="text-[13px] font-semibold text-ink-900">
                  {status.mode === 'live' ? 'Live account connected' : 'Test account connected'}
                </p>
                <p className="text-[11px] text-ink-500">
                  {status.connected_at
                    ? `Connected ${formatDate(status.connected_at)}`
                    : 'Connection active'}
                </p>
              </div>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Detail label="Mode" value={status.mode ? titleCase(status.mode) : '—'} />
              <Detail label="Integration ID" value={status.integration_id ?? '—'} mono />
              <Detail
                label="Connected at"
                value={status.connected_at ? formatDateTime(status.connected_at) : '—'}
              />
              <Detail
                label="Transaction sync"
                value={status.mode === 'live' ? 'Live' : 'Test data'}
              />
            </div>
            {status.mode === 'test' ? (
              <div className="flex items-start gap-2 rounded-xl bg-amber-50 px-4 py-3 text-[11px] leading-5 text-amber-800 ring-1 ring-inset ring-amber-200">
                <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                This workspace is using test transactions. Switch to a live key before relying on
                reconciliation or trust signals.
              </div>
            ) : null}
            {!showReplaceConfirm ? (
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => setShowReplaceConfirm(true)}>
                  <RefreshCcw className="h-3.5 w-3.5" /> Replace key
                </Button>
                <Link href="/onboarding">
                  <Button variant="ghost">View setup checklist</Button>
                </Link>
              </div>
            ) : (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                <p className="text-[12px] font-semibold text-amber-900">
                  Replace your Paystack key?
                </p>
                <p className="mt-1 text-[11px] leading-5 text-amber-800">
                  Existing transactions stay intact. New syncs use the new key immediately. Make
                  sure it belongs to the same Paystack account.
                </p>
                <div className="mt-3 flex gap-2">
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => {
                      setReplaceMode(true);
                      setShowReplaceConfirm(false);
                    }}
                  >
                    Continue
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setShowReplaceConfirm(false)}>
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </CardBody>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="bg-navy px-5 py-6 text-white sm:px-6">
            <div className="flex items-center gap-2 text-brand-300">
              <CreditCard className="h-4 w-4" />
              <p className="text-[10px] font-semibold uppercase tracking-[0.06em]">
                Connect in one step
              </p>
            </div>
            <h2 className="mt-3 text-xl font-semibold tracking-[-0.03em]">
              Paste your Paystack secret key
            </h2>
            <p className="mt-1.5 max-w-lg text-[12px] leading-6 text-ink-300">
              We&apos;ll verify it, encrypt it, and start importing your transaction history. This
              usually takes less than a minute.
            </p>
          </div>
          <CardBody className="space-y-4 pt-5">
            <div className="flex flex-wrap gap-3 text-[11px] text-ink-500">
              <span className="inline-flex items-center gap-1.5">
                <Lock className="h-3 w-3 text-brand-600" /> Encrypted at rest
              </span>
              <span className="inline-flex items-center gap-1.5">
                <KeyRound className="h-3 w-3 text-brand-600" /> Never returned by the API
              </span>
              <span className="inline-flex items-center gap-1.5">
                <ShieldCheck className="h-3 w-3 text-brand-600" /> Read-only usage
              </span>
            </div>
            <div className="rounded-xl bg-ink-50 p-4 text-[11px] leading-5 text-ink-600">
              Find it in Paystack Dashboard → Settings → API Keys &amp; Webhooks. Use the{' '}
              <span className="font-semibold text-ink-800">Secret Key</span>, not the public key.
            </div>
          </CardBody>
        </Card>
      )}

      {showForm ? (
        <Card>
          <CardHeader
            title={status?.connected ? 'Enter a new secret key' : 'Secret key'}
            description="Use a live key for production data."
          />
          <CardBody>
            <form onSubmit={submit} className="space-y-4">
              <div>
                <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500">
                  Paystack secret key
                </label>
                <div className="relative">
                  <Input
                    type={showKey ? 'text' : 'password'}
                    value={secretKey}
                    onChange={(event) => {
                      setSecretKey(event.target.value);
                      setError(null);
                    }}
                    placeholder="sk_live_••••••••••••••••"
                    autoComplete="off"
                    spellCheck={false}
                    className="pr-12 font-mono text-[12px]"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey((value) => !value)}
                    className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-ink-400 hover:bg-ink-50 hover:text-ink-700"
                    aria-label={showKey ? 'Hide key' : 'Show key'}
                  >
                    {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                <div className="mt-1.5 flex items-center justify-between gap-2">
                  <p className="text-[10px] text-ink-400">Keys start with sk_test_ or sk_live_.</p>
                  {mode ? (
                    <span
                      className={cn(
                        'rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide',
                        mode === 'live'
                          ? 'bg-brand-50 text-brand-700'
                          : 'bg-amber-50 text-amber-700',
                      )}
                    >
                      {mode} key
                    </span>
                  ) : null}
                </div>
              </div>
              {error ? <Alert tone="danger">{error}</Alert> : null}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="submit"
                  loading={connectMutation.isPending}
                  disabled={!secretKey.trim()}
                >
                  {status?.connected ? 'Replace and reconnect' : 'Connect Paystack'}
                </Button>
                {status?.connected && replaceMode ? (
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => {
                      setReplaceMode(false);
                      setSecretKey('');
                      setError(null);
                    }}
                  >
                    Cancel
                  </Button>
                ) : null}
              </div>
              {replaceMode ? (
                <p className="text-[10px] text-ink-400">
                  Replacing the key does not delete transactions or trust history.
                </p>
              ) : null}
            </form>
          </CardBody>
        </Card>
      ) : null}

      {!status?.connected ? (
        <div className="flex items-start gap-2.5 rounded-xl border border-line bg-surface p-4">
          <Lock className="mt-0.5 h-4 w-4 shrink-0 text-ink-400" />
          <p className="text-[11px] leading-5 text-ink-500">
            DisputePilot uses your Paystack key solely to read transactions for reconciliation and
            evidence. We never initiate charges, refunds or transfers.
          </p>
        </div>
      ) : null}
    </div>
  );
}

function Detail({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-xl border border-line px-3.5 py-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-400">{label}</p>
      <p
        className={cn(
          'mt-1 truncate text-[12px] font-medium text-ink-900',
          mono && 'font-mono text-[11px]',
        )}
      >
        {value}
      </p>
    </div>
  );
}
