'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Check,
  Copy,
  ExternalLink,
  Eye,
  Globe2,
  History,
  Lightbulb,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiRequest, errorMessage } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDate, formatDateTime, timeAgo } from '@/lib/format';
import type {
  TrustActions,
  TrustHistory,
  TrustProfile,
  TrustSignals,
  PublicTrustPage,
} from '@/lib/types';
import { TRUST_LABELS, TRUST_TONE } from '@/lib/constants';
import { PageHeader } from '@/components/ui/page-header';
import { PageSkeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardBody, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Tabs } from '@/components/ui/tabs';
import { TrustHistoryChart } from '@/components/trust/trust-history-chart';

export default function TrustPage() {
  const queryClient = useQueryClient();
  const [historyDays, setHistoryDays] = useState('30');
  const [copied, setCopied] = useState<string | null>(null);

  const profileQuery = useQuery({
    queryKey: ['trust', 'profile'],
    queryFn: () => apiRequest<TrustProfile>('/trust/profile'),
  });
  const signalsQuery = useQuery({
    queryKey: ['trust', 'signals'],
    queryFn: () => apiRequest<TrustSignals>('/trust/signals'),
  });
  const actionsQuery = useQuery({
    queryKey: ['trust', 'actions'],
    queryFn: () => apiRequest<TrustActions>('/trust/actions'),
  });
  const historyQuery = useQuery({
    queryKey: ['trust', 'history', historyDays],
    queryFn: () => apiRequest<TrustHistory>(`/trust/history?days=${historyDays}`),
  });

  const toggleMutation = useMutation({
    mutationFn: (payload: { public_enabled?: boolean; widget_enabled?: boolean }) =>
      apiRequest<TrustProfile>('/trust/profile/settings', {
        method: 'PUT',
        body: payload,
      }),
    onSuccess: (profile) => {
      toast.success('Trust settings updated');
      queryClient.setQueryData(['trust', 'profile'], profile);
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const copy = async (value: string, key: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(key);
      toast.success('Copied to clipboard');
      window.setTimeout(() => setCopied(null), 2000);
    } catch {
      toast.error('Could not copy');
    }
  };

  if (profileQuery.isLoading) return <PageSkeleton />;
  if (profileQuery.isError || !profileQuery.data) {
    return (
      <div className="space-y-5">
        <PageHeader title="TrustLayer" />
        <Alert tone="danger" title="Could not load your trust profile">
          {errorMessage(profileQuery.error)}
        </Alert>
      </div>
    );
  }

  const profile = profileQuery.data;
  const signals = signalsQuery.data?.signals ?? profile.signals;
  const actions = actionsQuery.data?.actions ?? [];
  const publicPage: PublicTrustPage = {
    merchant_name: 'Your business',
    state: profile.state,
    label: profile.label,
    meaning: profile.meaning,
    verification_summary: profile.explanation ?? profile.meaning,
    payments_30d: profile.sample?.payments_30d ?? 0,
    window_days: 30,
    updated_at: profile.last_computed_at,
    stable_since: profile.stable_since,
  };
  const embedCode = `<iframe src="${profile.public_url}/badge" width="200" height="60" style="border:0" title="TrustLayer badge"></iframe>`;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Public proof"
        title="TrustLayer"
        description="Your operational trust profile, explained clearly and shared on your terms."
        actions={
          <>
            <Link href="/settings">
              <Button variant="outline">
                <Globe2 className="h-4 w-4" /> Public settings
              </Button>
            </Link>
            <a href={profile.public_url} target="_blank" rel="noreferrer">
              <Button disabled={!profile.public_enabled}>
                <ExternalLink className="h-4 w-4" /> Open public page
              </Button>
            </a>
          </>
        }
      />

      <div className="relative overflow-hidden rounded-3xl bg-ink-950 p-6 text-white shadow-float sm:p-8">
        <div className="absolute -right-20 -top-24 h-72 w-72 rounded-full bg-brand-500/20 blur-3xl" />
        <div className="absolute bottom-0 right-10 h-40 w-40 rounded-full bg-amber-300/10 blur-2xl" />
        <div className="relative grid gap-8 lg:grid-cols-[1.4fr_0.8fr] lg:items-end">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-bold uppercase tracking-wide ring-1 ring-inset',
                  TRUST_TONE[profile.state],
                )}
              >
                <ShieldCheck className="h-3.5 w-3.5" />
                {TRUST_LABELS[profile.state]}
              </span>
              <span className="text-[11px] text-ink-400">
                {profile.stable_since
                  ? `Stable since ${formatDate(profile.stable_since)}`
                  : 'First computation in progress'}
              </span>
            </div>
            <h2 className="mt-4 max-w-2xl text-balance text-3xl font-semibold leading-tight tracking-[-0.04em] sm:text-4xl">
              {profile.label}
            </h2>
            <p className="mt-3 max-w-2xl text-[14px] leading-7 text-ink-300">
              {profile.explanation ?? profile.meaning}
            </p>
            <div className="mt-5 flex flex-wrap gap-4 text-[12px] text-ink-300">
              <span>
                <span className="font-semibold text-white">
                  {profile.sample?.payments_30d ?? 0}
                </span>{' '}
                payments in 30 days
              </span>
              <span>
                <span className="font-semibold text-white">
                  {profile.sample?.days_on_platform ?? 0}
                </span>{' '}
                days on DisputePilot
              </span>
              <span>
                Updated {profile.last_computed_at ? timeAgo(profile.last_computed_at) : '—'}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-400">
                Internal score
              </p>
              <p className="mt-1 text-3xl font-semibold tracking-[-0.04em]">
                {profile.internal_score ?? '—'}
              </p>
              <p className="mt-1 text-[10px] text-ink-400">Merchant-only</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.06] p-4">
              <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-400">
                Public page
              </p>
              <p className="mt-1 text-lg font-semibold">
                {profile.public_enabled ? 'Live' : 'Off'}
              </p>
              <p className="mt-1 text-[10px] text-ink-400">
                Widget {profile.widget_enabled ? 'enabled' : 'disabled'}
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader
            title="Signal breakdown"
            description="Deterministic policy signals, each mapped to the next threshold."
            action={
              signalsQuery.data?.next_state ? (
                <Badge tone="info">Next: {TRUST_LABELS[signalsQuery.data.next_state]}</Badge>
              ) : null
            }
          />
          <CardBody className="space-y-5">
            {signals.map((signal) => {
              const tone =
                signal.reading === 'strong'
                  ? 'brand'
                  : signal.reading === 'fair'
                    ? 'amber'
                    : signal.reading === 'weak'
                      ? 'red'
                      : 'ink';
              return (
                <div key={signal.key}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-[13px] font-semibold text-ink-900">{signal.label}</p>
                      <p className="mt-0.5 text-[11px] text-ink-400">
                        {signal.reading === 'insufficient'
                          ? 'Not enough data yet'
                          : signal.reading === 'strong'
                            ? 'Meets the Verified threshold'
                            : signal.reading === 'fair'
                              ? 'Building — below Verified'
                              : 'Below the Building threshold'}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-[15px] font-semibold text-ink-950">
                        {signal.value === null ? '—' : `${signal.value.toFixed(0)}%`}
                      </p>
                      {signal.verified_threshold ? (
                        <p className="text-[10px] text-ink-400">
                          Verified {signal.verified_threshold}
                        </p>
                      ) : null}
                    </div>
                  </div>
                  <Progress value={signal.value} tone={tone} className="mt-2.5" />
                  {signal.action ? (
                    <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-4 text-ink-500">
                      <Lightbulb className="mt-0.5 h-3 w-3 shrink-0 text-amber-500" />
                      {signal.action}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </CardBody>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Recommended next moves"
              description="Written by AI from your weakest signals."
              action={<Sparkles className="h-4 w-4 text-brand-600" />}
            />
            <CardBody>
              {actions.length ? (
                <div className="space-y-3">
                  {actions.map((action, index) => (
                    <div
                      key={`${action.action}-${index}`}
                      className="rounded-xl border border-line p-3.5"
                    >
                      <div className="flex items-start gap-2.5">
                        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-[10px] font-bold text-brand-700">
                          {index + 1}
                        </span>
                        <div>
                          <p className="text-[12px] font-semibold text-ink-900">{action.action}</p>
                          <p className="mt-1 text-[11px] leading-5 text-ink-500">
                            {action.impact_description}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-xl bg-ink-50 px-4 py-6 text-center">
                  <p className="text-[12px] font-medium text-ink-600">No recommendations yet</p>
                  <p className="mt-1 text-[11px] text-ink-400">
                    AI actions appear after your next trust computation.
                  </p>
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Public page controls" />
            <CardBody className="space-y-4">
              <ToggleRow
                label="Public trust page"
                description="Let customers open your verification page."
                enabled={profile.public_enabled}
                loading={toggleMutation.isPending}
                onToggle={(value) => toggleMutation.mutate({ public_enabled: value })}
              />
              <ToggleRow
                label="Embeddable badge"
                description="Show the TrustLayer badge on your website."
                enabled={profile.widget_enabled}
                loading={toggleMutation.isPending}
                onToggle={(value) => toggleMutation.mutate({ widget_enabled: value })}
              />
              <div className="border-t border-line pt-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500">
                  Public URL
                </p>
                <div className="mt-2 flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded-lg bg-ink-50 px-2.5 py-2 text-[11px] text-ink-600">
                    {profile.public_url}
                  </code>
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => copy(profile.public_url, 'url')}
                    aria-label="Copy public URL"
                  >
                    {copied === 'url' ? (
                      <Check className="h-4 w-4 text-brand-600" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                  </Button>
                </div>
                <p className="mt-4 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-500">
                  Embed code
                </p>
                <div className="mt-2 flex items-start gap-2">
                  <code className="min-w-0 flex-1 break-all rounded-lg bg-ink-50 px-2.5 py-2 text-[11px] leading-5 text-ink-600">
                    {embedCode}
                  </code>
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => copy(embedCode, 'embed')}
                    aria-label="Copy embed code"
                  >
                    {copied === 'embed' ? (
                      <Check className="h-4 w-4 text-brand-600" />
                    ) : (
                      <Copy className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              </div>
            </CardBody>
          </Card>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader
            title="Trust history"
            description="Score snapshots and state changes over time."
            action={
              <Tabs
                items={[
                  { value: '7', label: '7d' },
                  { value: '30', label: '30d' },
                  { value: '90', label: '90d' },
                ]}
                value={historyDays}
                onChange={setHistoryDays}
              />
            }
          />
          <CardBody className="pt-2">
            <TrustHistoryChart history={historyQuery.data} />
            {historyQuery.data?.changes.length ? (
              <div className="mt-4 space-y-2 border-t border-line pt-4">
                {historyQuery.data.changes
                  .slice(-4)
                  .reverse()
                  .map((change) => (
                    <div
                      key={`${change.at}-${change.to_state}`}
                      className="flex items-start gap-2.5"
                    >
                      <History className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-400" />
                      <div>
                        <p className="text-[12px] font-medium text-ink-800">
                          {change.from_state ? `${TRUST_LABELS[change.from_state]} → ` : ''}
                          {TRUST_LABELS[change.to_state]}
                        </p>
                        <p className="text-[11px] text-ink-400">
                          {formatDateTime(change.at)} · {change.summary ?? change.reason}
                        </p>
                      </div>
                    </div>
                  ))}
              </div>
            ) : null}
          </CardBody>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader
            title="Public page preview"
            description="What customers see when they visit your link."
            action={
              <a href={profile.public_url} target="_blank" rel="noreferrer">
                <Button variant="ghost" size="sm" disabled={!profile.public_enabled}>
                  <Eye className="h-3.5 w-3.5" /> Preview
                </Button>
              </a>
            }
          />
          <CardBody>
            <div className="rounded-2xl border border-line bg-gradient-to-br from-white to-brand-50/50 p-5">
              <div className="flex items-center gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-500 text-white">
                  <ShieldCheck className="h-5 w-5" />
                </div>
                <div>
                  <p className="text-[13px] font-semibold text-ink-950">Your business</p>
                  <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-brand-700">
                    TrustLayer {TRUST_LABELS[profile.state]}
                  </p>
                </div>
              </div>
              <p className="mt-4 text-[12px] leading-6 text-ink-600">
                {publicPage.verification_summary}
              </p>
              <p className="mt-3 text-[10px] text-ink-400">
                Based on {publicPage.payments_30d} payments over the last 30 days.
              </p>
            </div>
            <p className="mt-3 text-[10px] leading-5 text-ink-400">
              The public page never exposes your score, dispute details, customer data or raw signal
              percentages.
            </p>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function ToggleRow({
  label,
  description,
  enabled,
  loading,
  onToggle,
}: {
  label: string;
  description: string;
  enabled: boolean;
  loading: boolean;
  onToggle: (value: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <p className="text-[13px] font-semibold text-ink-900">{label}</p>
        <p className="mt-0.5 text-[11px] leading-5 text-ink-500">{description}</p>
      </div>
      <button
        type="button"
        disabled={loading}
        onClick={() => onToggle(!enabled)}
        className={cn(
          'relative h-6 w-11 shrink-0 rounded-full transition',
          enabled ? 'bg-brand-600' : 'bg-ink-200',
        )}
        aria-pressed={enabled}
        aria-label={label}
      >
        <span
          className={cn(
            'absolute top-1 h-4 w-4 rounded-full bg-white shadow transition',
            enabled ? 'left-6' : 'left-1',
          )}
        />
      </button>
    </div>
  );
}
