'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowRight,
  Bell,
  Check,
  CheckCircle2,
  CreditCard,
  Loader2,
  PartyPopper,
  RefreshCcw,
  ShieldCheck,
  Sparkles,
  Wallet,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiRequest, errorMessage } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDateTime } from '@/lib/format';
import type { Merchant, Onboarding, Settings } from '@/lib/types';
import { PageHeader } from '@/components/ui/page-header';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';

const STEPS = [
  {
    key: 'connect_paystack',
    label: 'Connect Paystack',
    description: 'Link the account that receives payments.',
  },
  {
    key: 'configure_notifications',
    label: 'Notifications',
    description: 'Choose how we alert you.',
  },
  {
    key: 'initial_sync',
    label: 'Import transactions',
    description: 'We pull your payment history.',
  },
  {
    key: 'first_reconciliation',
    label: 'First reconciliation',
    description: 'Match payments to orders.',
  },
] as const;

type StepKey = (typeof STEPS)[number]['key'];

const ORDER: StepKey[] = [
  'connect_paystack',
  'configure_notifications',
  'initial_sync',
  'first_reconciliation',
];

export default function OnboardingPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [notifyEmail, setNotifyEmail] = useState(true);

  const onboardingQuery = useQuery({
    queryKey: ['onboarding'],
    queryFn: () => apiRequest<Onboarding>('/onboarding'),
    refetchInterval: (query) => {
      const data = query.state.data as Onboarding | undefined;
      return data && !data.completed && data.next_step === 'initial_sync' ? 2000 : false;
    },
  });
  const merchantQuery = useQuery({
    queryKey: ['merchant', 'me'],
    queryFn: () => apiRequest<Merchant>('/auth/me'),
  });
  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiRequest<Settings>('/settings'),
  });

  useEffect(() => {
    if (settingsQuery.data) setNotifyEmail(settingsQuery.data.notification_email);
  }, [settingsQuery.data]);

  const notificationsMutation = useMutation({
    mutationFn: (value: boolean) =>
      apiRequest<Onboarding>('/onboarding/notifications', {
        method: 'POST',
        body: { notification_email: value },
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(['onboarding'], data);
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      toast.success('Notifications saved — importing transactions');
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const skipMutation = useMutation({
    mutationFn: () =>
      apiRequest<Onboarding>('/onboarding/first-reconciliation/skip', { method: 'POST' }),
    onSuccess: (data) => {
      queryClient.setQueryData(['onboarding'], data);
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      toast.success('Onboarding complete');
      router.push('/');
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (onboardingQuery.isLoading || merchantQuery.isLoading) {
    return (
      <div className="flex h-72 flex-col items-center justify-center gap-3">
        <Loader2 className="h-6 w-6 animate-spin text-brand-600" />
        <p className="text-[12px] text-ink-500">Checking your setup progress</p>
      </div>
    );
  }

  if (onboardingQuery.isError || !onboardingQuery.data) {
    return (
      <div className="space-y-5">
        <PageHeader title="Finish setup" />
        <Alert tone="danger" title="Could not load onboarding">
          {errorMessage(onboardingQuery.error)}
        </Alert>
      </div>
    );
  }

  const onboarding = onboardingQuery.data;
  const merchant = merchantQuery.data;
  const currentIndex = onboarding.completed
    ? STEPS.length
    : Math.max(0, ORDER.indexOf(onboarding.next_step as StepKey));
  const completion = Math.round((currentIndex / STEPS.length) * 100);
  const paystackConnected = Boolean(merchant?.paystack.connected);
  const syncInProgress = onboarding.initial_sync_status === 'in_progress';
  const syncFailed = onboarding.initial_sync_status === 'failed';
  const syncProgress =
    onboarding.initial_sync_total && onboarding.initial_sync_total > 0
      ? Math.min(
          100,
          Math.round((onboarding.initial_sync_processed / onboarding.initial_sync_total) * 100),
        )
      : null;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader
        eyebrow="Getting started"
        title={onboarding.completed ? 'You’re all set' : 'Finish setting up your workspace'}
        description="Four short steps. Your workspace starts producing evidence immediately after."
        actions={
          onboarding.completed ? (
            <Link href="/">
              <Button>
                Go to dashboard <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          ) : (
            <Badge tone="info">{completion}% complete</Badge>
          )
        }
      />

      {!onboarding.completed ? (
        <div className="rounded-2xl border border-line bg-white p-4">
          <div className="flex items-center justify-between text-[11px] font-medium text-ink-500">
            <span>
              Step {Math.min(currentIndex + 1, STEPS.length)} of {STEPS.length}
            </span>
            <span>{completion}%</span>
          </div>
          <Progress value={completion} className="mt-2" />
        </div>
      ) : null}

      <div className="grid gap-6 md:grid-cols-[250px_1fr]">
        <div className="space-y-2">
          {STEPS.map((step, index) => {
            const state = onboarding.completed
              ? 'done'
              : index < currentIndex
                ? 'done'
                : index === currentIndex
                  ? 'active'
                  : 'upcoming';
            return (
              <div
                key={step.key}
                className={cn(
                  'flex items-start gap-3 rounded-xl border px-3 py-3 transition',
                  state === 'active'
                    ? 'border-brand-200 bg-brand-50/70'
                    : 'border-transparent bg-transparent',
                )}
              >
                <span
                  className={cn(
                    'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold',
                    state === 'done'
                      ? 'bg-brand-600 text-white'
                      : state === 'active'
                        ? 'bg-ink-950 text-white'
                        : 'bg-ink-100 text-ink-400',
                  )}
                >
                  {state === 'done' ? <Check className="h-3.5 w-3.5" /> : index + 1}
                </span>
                <div>
                  <p
                    className={cn(
                      'text-[12px] font-semibold',
                      state === 'upcoming' ? 'text-ink-400' : 'text-ink-900',
                    )}
                  >
                    {step.label}
                  </p>
                  <p className="mt-0.5 text-[10px] leading-4 text-ink-400">{step.description}</p>
                </div>
              </div>
            );
          })}
        </div>

        <div>
          {onboarding.completed ? (
            <Card>
              <CardBody className="py-10 text-center">
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-500 text-white">
                  <PartyPopper className="h-6 w-6" />
                </div>
                <h2 className="mt-4 text-xl font-semibold tracking-[-0.03em] text-ink-950">
                  Your workspace is ready
                </h2>
                <p className="mx-auto mt-2 max-w-sm text-[12px] leading-6 text-ink-500">
                  Transactions are imported, reconciliation is available and your trust profile is
                  building. Log fulfillments as they happen to win more disputes.
                </p>
                {onboarding.completed_at ? (
                  <p className="mt-3 text-[10px] text-ink-400">
                    Completed {formatDateTime(onboarding.completed_at)}
                  </p>
                ) : null}
                <div className="mt-6 flex flex-wrap justify-center gap-2">
                  <Link href="/">
                    <Button>
                      Open dashboard <ArrowRight className="h-4 w-4" />
                    </Button>
                  </Link>
                  <Link href="/reconciliation">
                    <Button variant="outline">Start reconciling</Button>
                  </Link>
                </div>
              </CardBody>
            </Card>
          ) : onboarding.next_step === 'connect_paystack' ? (
            <Card>
              <CardHeader
                title="Connect Paystack"
                description="DisputePilot reads your settled payments to match them with orders."
                action={<CreditCard className="h-4 w-4 text-brand-600" />}
              />
              <CardBody className="space-y-5">
                <div className="rounded-2xl bg-ink-950 p-5 text-white">
                  <div className="flex items-center gap-2 text-brand-300">
                    <Wallet className="h-4 w-4" />
                    <p className="text-[10px] font-semibold uppercase tracking-[0.12em]">
                      Read-only access
                    </p>
                  </div>
                  <p className="mt-2 text-[13px] leading-6 text-ink-200">
                    Paste your Paystack secret key once. It is encrypted, never returned, and used
                    only to read transactions.
                  </p>
                </div>
                <ul className="space-y-2.5">
                  {[
                    'Import settled and pending transactions automatically',
                    'Reconcile payments against your orders',
                    'Build the evidence needed for disputes and trust',
                  ].map((item) => (
                    <li key={item} className="flex items-start gap-2 text-[12px] text-ink-600">
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-600" />
                      {item}
                    </li>
                  ))}
                </ul>
                <div className="flex flex-wrap gap-2">
                  <Link href="/settings/paystack">
                    <Button>
                      <CreditCard className="h-4 w-4" /> Connect Paystack
                    </Button>
                  </Link>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      merchantQuery.refetch();
                      onboardingQuery.refetch();
                    }}
                    loading={merchantQuery.isFetching || onboardingQuery.isFetching}
                  >
                    <RefreshCcw className="h-3.5 w-3.5" /> I already connected
                  </Button>
                </div>
              </CardBody>
            </Card>
          ) : onboarding.next_step === 'configure_notifications' ? (
            <Card>
              <CardHeader
                title="Choose your notifications"
                description="Timely alerts are the difference between a won and lost dispute."
                action={<Bell className="h-4 w-4 text-brand-600" />}
              />
              <CardBody className="space-y-5">
                <div className="flex items-start justify-between gap-4 rounded-xl border border-line p-4">
                  <div className="flex items-start gap-2.5">
                    <Bell className="mt-0.5 h-4 w-4 text-ink-500" />
                    <div>
                      <p className="text-[13px] font-semibold text-ink-900">Email alerts</p>
                      <p className="mt-0.5 text-[11px] leading-5 text-ink-500">
                        New disputes, evidence deadlines within 48 hours, and status changes.
                      </p>
                    </div>
                  </div>
                  <Switch checked={notifyEmail} onChange={setNotifyEmail} label="Email alerts" />
                </div>
                <p className="text-[11px] leading-5 text-ink-400">
                  You can change this any time in Settings. In-app deadline reminders are always on.
                </p>
                <Button
                  onClick={() => notificationsMutation.mutate(notifyEmail)}
                  loading={notificationsMutation.isPending}
                >
                  Save and import transactions <ArrowRight className="h-4 w-4" />
                </Button>
              </CardBody>
            </Card>
          ) : onboarding.next_step === 'initial_sync' ? (
            <Card>
              <CardBody className="py-8">
                <div className="text-center">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-700">
                    {syncInProgress ? (
                      <Loader2 className="h-5 w-5 animate-spin" />
                    ) : syncFailed ? (
                      <RefreshCcw className="h-5 w-5 text-danger" />
                    ) : (
                      <CheckCircle2 className="h-5 w-5" />
                    )}
                  </div>
                  <h2 className="mt-4 text-lg font-semibold tracking-[-0.02em] text-ink-950">
                    {syncInProgress
                      ? 'Importing your transactions'
                      : syncFailed
                        ? 'Import failed'
                        : 'Transactions imported'}
                  </h2>
                  <p className="mx-auto mt-1.5 max-w-sm text-[12px] leading-6 text-ink-500">
                    {syncInProgress
                      ? 'You can leave this page — the import continues in the background. We’ll pick up where you left off.'
                      : syncFailed
                        ? 'Something went wrong while importing. Try saving notifications again, or contact support if it keeps failing.'
                        : 'Your payment history is ready. Next, match it to your orders.'}
                  </p>
                </div>
                <div className="mx-auto mt-6 max-w-sm">
                  <div className="flex items-center justify-between text-[11px] text-ink-500">
                    <span>Progress</span>
                    <span>
                      {onboarding.initial_sync_processed}
                      {onboarding.initial_sync_total ? ` / ${onboarding.initial_sync_total}` : ''}
                    </span>
                  </div>
                  <Progress
                    value={syncProgress}
                    tone={syncFailed ? 'red' : 'brand'}
                    className="mt-2"
                  />
                  {syncProgress === null && syncInProgress ? (
                    <p className="mt-2 text-center text-[10px] text-ink-400">Calculating totals…</p>
                  ) : null}
                </div>
                <div className="mt-6 flex flex-wrap justify-center gap-2">
                  <Button
                    variant="outline"
                    onClick={() => onboardingQuery.refetch()}
                    loading={onboardingQuery.isFetching}
                  >
                    <RefreshCcw className="h-3.5 w-3.5" /> Refresh
                  </Button>
                  {syncFailed ? (
                    <Button
                      variant="ghost"
                      onClick={() => notificationsMutation.mutate(notifyEmail)}
                    >
                      Retry import
                    </Button>
                  ) : null}
                </div>
              </CardBody>
            </Card>
          ) : (
            <Card>
              <CardHeader
                title="Run your first reconciliation"
                description="Match imported payments to orders and flag anything that needs attention."
                action={<Sparkles className="h-4 w-4 text-brand-600" />}
              />
              <CardBody className="space-y-5">
                <div className="grid gap-3 sm:grid-cols-3">
                  {[
                    ['1', 'Match exact payments', 'Amount, date and reference line up.'],
                    ['2', 'Review suggestions', 'We suggest matches with a confidence score.'],
                    ['3', 'Flag the rest', 'Unmatched payments become follow-up tasks.'],
                  ].map(([number, title, description]) => (
                    <div key={number} className="rounded-xl border border-line p-3.5">
                      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-ink-950 text-[10px] font-bold text-white">
                        {number}
                      </span>
                      <p className="mt-2 text-[11px] font-semibold text-ink-900">{title}</p>
                      <p className="mt-0.5 text-[10px] leading-4 text-ink-500">{description}</p>
                    </div>
                  ))}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Link href="/reconciliation">
                    <Button>
                      Start reconciliation <ArrowRight className="h-4 w-4" />
                    </Button>
                  </Link>
                  <Button
                    variant="ghost"
                    loading={skipMutation.isPending}
                    onClick={() => skipMutation.mutate()}
                  >
                    I&apos;ll do this later
                  </Button>
                </div>
              </CardBody>
            </Card>
          )}
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-2xl border border-line bg-white px-4 py-3.5">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" />
        <p className="text-[11px] leading-5 text-ink-500">
          {paystackConnected
            ? 'Paystack is connected. You can rotate the key any time from Settings.'
            : 'Your setup can be paused and resumed at any point. Everything is saved as you go.'}
        </p>
      </div>
    </div>
  );
}
