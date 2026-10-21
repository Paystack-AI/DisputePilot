'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Bell,
  Building2,
  CreditCard,
  Globe2,
  Loader2,
  RefreshCcw,
  Save,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiRequest, errorMessage } from '@/lib/api';
import { formatDate, titleCase } from '@/lib/format';
import type { Currency, Merchant, Settings } from '@/lib/types';
import { CURRENCIES } from '@/lib/constants';
import { PageHeader } from '@/components/ui/page-header';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { PageSkeleton } from '@/components/ui/skeleton';
import { WebhookCard } from '@/components/settings/webhook-card';

const TIMEZONES = [
  'Africa/Lagos',
  'Africa/Accra',
  'Africa/Abidjan',
  'Africa/Nairobi',
  'Africa/Johannesburg',
  'Africa/Cairo',
  'Europe/London',
  'Europe/Paris',
  'America/New_York',
  'America/Los_Angeles',
  'Asia/Dubai',
  'UTC',
];

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Settings | null>(null);

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiRequest<Settings>('/settings'),
  });
  const merchantQuery = useQuery({
    queryKey: ['merchant', 'me'],
    queryFn: () => apiRequest<Merchant>('/auth/me'),
  });
  const merchant = merchantQuery.data;

  useEffect(() => {
    if (settingsQuery.data) setForm(settingsQuery.data);
  }, [settingsQuery.data]);

  const saveMutation = useMutation({
    mutationFn: (payload: Partial<Settings>) =>
      apiRequest<Settings>('/settings', { method: 'PATCH', body: payload }),
    onSuccess: (settings) => {
      queryClient.setQueryData(['settings'], settings);
      queryClient.invalidateQueries({ queryKey: ['trust'] });
      setForm(settings);
      toast.success('Settings saved');
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  if (settingsQuery.isLoading || !form) return <PageSkeleton />;
  if (settingsQuery.isError) {
    return (
      <div className="space-y-5">
        <PageHeader title="Settings" />
        <Alert tone="danger" title="Could not load settings">
          {errorMessage(settingsQuery.error)}
        </Alert>
      </div>
    );
  }

  const set = <K extends keyof Settings>(key: K, value: Settings[K]) =>
    setForm((current) => (current ? { ...current, [key]: value } : current));

  const save = () => {
    saveMutation.mutate({
      notification_email: form.notification_email,
      auto_reconciliation_tier1: form.auto_reconciliation_tier1,
      default_reconciliation_range: form.default_reconciliation_range,
      trust_public_enabled: form.trust_public_enabled,
      trust_widget_enabled: form.trust_widget_enabled,
      timezone: form.timezone,
      default_currency: form.default_currency,
    });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Your account"
        title="Settings"
        description="Preferences, notifications and the defaults that power reconciliation."
        actions={
          <Button onClick={save} loading={saveMutation.isPending}>
            <Save className="h-4 w-4" /> Save changes
          </Button>
        }
      />

      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Business profile"
              description="How your trust page identifies you."
            />
            <CardBody className="space-y-4">
              <div className="flex items-center gap-3">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-50 text-brand-700">
                  <Building2 className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-[14px] font-semibold text-ink-950">
                    {merchant?.business_name ?? 'Your business'}
                  </p>
                  <p className="text-[11px] text-ink-500">
                    {merchant?.email ?? merchant?.google_email ?? 'No email on file'}
                  </p>
                </div>
              </div>
              <div className="grid gap-3 rounded-xl bg-ink-50/70 p-4 text-[12px] sm:grid-cols-2">
                <Info
                  label="Merchant since"
                  value={merchant?.created_at ? formatDate(merchant.created_at) : '—'}
                />
                <Info label="Currency" value={form.default_currency} />
                <Info label="Timezone" value={form.timezone} />
                <Info
                  label="Onboarding"
                  value={merchant?.onboarding.completed ? 'Completed' : 'In progress'}
                />
              </div>
              <Link href="/settings/account">
                <Button variant="outline" size="sm">
                  Manage account <span aria-hidden>→</span>
                </Button>
              </Link>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Reconciliation defaults"
              description="Applied whenever you start a new reconciliation session."
              action={<RefreshCcw className="h-4 w-4 text-ink-400" />}
            />
            <CardBody className="space-y-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500">
                    Lookback window
                  </label>
                  <Select
                    value={String(form.default_reconciliation_range)}
                    onChange={(event) =>
                      set('default_reconciliation_range', Number(event.target.value))
                    }
                  >
                    {[7, 14, 30, 45, 60, 90].map((days) => (
                      <option key={days} value={days}>
                        Last {days} days
                      </option>
                    ))}
                  </Select>
                </div>
                <div>
                  <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500">
                    Default currency
                  </label>
                  <Select
                    value={form.default_currency}
                    onChange={(event) => set('default_currency', event.target.value as Currency)}
                  >
                    {CURRENCIES.map((currency) => (
                      <option key={currency} value={currency}>
                        {currency}
                      </option>
                    ))}
                  </Select>
                </div>
              </div>
              <SettingRow
                title="Auto-accept Tier 1 matches"
                description="When exact amount, date and reference line up, accept the match without review."
                checked={form.auto_reconciliation_tier1}
                onChange={(value) => set('auto_reconciliation_tier1', value)}
                icon={<Sparkles className="h-4 w-4 text-brand-600" />}
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="Notifications"
              description="Choose how we reach you about time-sensitive work."
            />
            <CardBody className="space-y-5">
              <SettingRow
                title="Dispute and deadline emails"
                description="New disputes, deadlines within 48 hours, and evidence status updates."
                checked={form.notification_email}
                onChange={(value) => set('notification_email', value)}
                icon={<Bell className="h-4 w-4 text-ink-500" />}
              />
              <div className="rounded-xl bg-amber-50 px-4 py-3 text-[11px] leading-5 text-amber-800 ring-1 ring-inset ring-amber-200">
                Deadlines are always enforced on your DisputePilot dashboard, even if email is off.
                Email improves response time and protects your win rate.
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="TrustLayer"
              description="Control what customers can see."
              action={<ShieldCheck className="h-4 w-4 text-brand-600" />}
            />
            <CardBody className="space-y-5">
              <SettingRow
                title="Public trust page"
                description="A shareable page showing your verified operational behaviour."
                checked={form.trust_public_enabled}
                onChange={(value) => set('trust_public_enabled', value)}
                icon={<Globe2 className="h-4 w-4 text-brand-600" />}
              />
              <SettingRow
                title="Embeddable badge"
                description="Display your trust state on your own website."
                checked={form.trust_widget_enabled}
                onChange={(value) => set('trust_widget_enabled', value)}
                icon={<ShieldCheck className="h-4 w-4 text-brand-600" />}
              />
              <Link href="/trust">
                <Button variant="outline" size="sm">
                  Open TrustLayer <span aria-hidden>→</span>
                </Button>
              </Link>
            </CardBody>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader title="Payment source" />
            <CardBody className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-canvas text-ink-600 ring-1 ring-inset ring-line">
                    <CreditCard className="h-4 w-4" />
                  </div>
                  <div>
                    <p className="text-[12px] font-semibold text-ink-900">Paystack</p>
                    <p className="text-[10px] text-ink-400">Transaction sync</p>
                  </div>
                </div>
                <Badge tone={merchant?.paystack.connected ? 'success' : 'neutral'}>
                  {merchant?.paystack.connected ? 'Connected' : 'Not connected'}
                </Badge>
              </div>
              {merchant?.paystack.connected ? (
                <div className="space-y-1.5 rounded-xl bg-ink-50/70 px-3 py-2.5 text-[11px]">
                  <div className="flex justify-between gap-2">
                    <span className="text-ink-500">Mode</span>
                    <span className="font-medium text-ink-800">
                      {merchant.paystack.mode ? titleCase(merchant.paystack.mode) : '—'}
                    </span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="text-ink-500">Connected</span>
                    <span className="font-medium text-ink-800">
                      {merchant.paystack.connected_at
                        ? formatDate(merchant.paystack.connected_at)
                        : '—'}
                    </span>
                  </div>
                </div>
              ) : null}
              <Link href="/settings/paystack" className="block">
                <Button variant="outline" className="w-full">
                  {merchant?.paystack.connected ? 'Manage connection' : 'Connect Paystack'}
                </Button>
              </Link>
            </CardBody>
          </Card>

          <WebhookCard />

          <Card>
            <CardHeader title="Workspace defaults" />
            <CardBody className="space-y-4">
              <div>
                <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500">
                  Timezone
                </label>
                <Select
                  value={form.timezone}
                  onChange={(event) => set('timezone', event.target.value)}
                >
                  {Array.from(new Set([form.timezone, ...TIMEZONES])).map((timezone) => (
                    <option key={timezone} value={timezone}>
                      {timezone}
                    </option>
                  ))}
                </Select>
                <p className="mt-1.5 text-[10px] leading-4 text-ink-400">
                  Deadlines and daily summaries are calculated in this timezone.
                </p>
              </div>
              {form.updated_at ? (
                <p className="text-[10px] text-ink-400">Last saved {formatDate(form.updated_at)}</p>
              ) : null}
            </CardBody>
          </Card>

          <div className="flex items-start gap-2 rounded-2xl bg-white p-4 text-[11px] leading-5 text-ink-500 ring-1 ring-inset ring-line">
            <Loader2
              className={saveMutation.isPending ? 'mt-0.5 h-3.5 w-3.5 animate-spin' : 'hidden'}
            />
            <p>
              Settings apply immediately after saving. Changing timezone or currency does not
              rewrite historical records.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function SettingRow({
  title,
  description,
  checked,
  onChange,
  icon,
}: {
  title: string;
  description: string;
  checked: boolean;
  onChange: (value: boolean) => void;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div className="flex items-start gap-2.5">
        {icon ? <span className="mt-0.5">{icon}</span> : null}
        <div>
          <p className="text-[13px] font-semibold text-ink-900">{title}</p>
          <p className="mt-0.5 max-w-md text-[11px] leading-5 text-ink-500">{description}</p>
        </div>
      </div>
      <Switch checked={checked} onChange={onChange} label={title} />
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-400">{label}</p>
      <p className="mt-0.5 font-medium text-ink-800">{value}</p>
    </div>
  );
}
