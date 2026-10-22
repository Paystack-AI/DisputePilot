'use client';

import { useParams } from 'next/navigation';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import {
  BadgeCheck,
  CalendarDays,
  CheckCircle2,
  FileCheck2,
  Lock,
  ReceiptText,
  ShieldCheck,
  Truck,
} from 'lucide-react';
import { ApiError, apiRequest } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDate, timeAgo } from '@/lib/format';
import { TRUST_LABELS, TRUST_TONE } from '@/lib/constants';
import type { PublicTrustPage } from '@/lib/types';
import { Brand } from '@/components/brand';

const CHECKS = [
  {
    icon: ReceiptText,
    title: 'Payments reconciled',
    description: 'Settlements are matched to real orders — not guessed.',
  },
  {
    icon: Truck,
    title: 'Fulfillment recorded',
    description: 'Deliveries are logged with timestamps and photo proof.',
  },
  {
    icon: FileCheck2,
    title: 'Disputes handled on time',
    description: 'Disputes are answered with structured evidence before deadlines.',
  },
];

export default function PublicTrustPageView() {
  const params = useParams<{ token: string }>();
  const token = params?.token;
  const query = useQuery({
    queryKey: ['public-trust', token],
    queryFn: () => apiRequest<PublicTrustPage>(`/public/trust/${token}`),
    enabled: Boolean(token),
    retry: false,
  });

  if (query.isLoading) {
    return (
      <PublicFrame>
        <div className="relative overflow-hidden rounded-xl border border-line bg-surface p-8 shadow-soft">
          <div className="animate-pulse space-y-4">
            <div className="h-12 w-12 rounded-xl bg-ink-100" />
            <div className="h-4 w-40 rounded bg-ink-100" />
            <div className="h-8 w-72 rounded bg-ink-100" />
            <div className="h-4 w-full rounded bg-ink-100" />
            <div className="h-4 w-2/3 rounded bg-ink-100" />
          </div>
        </div>
      </PublicFrame>
    );
  }

  if (query.isError || !query.data) {
    const notFound = query.error instanceof ApiError && query.error.status === 404;
    return (
      <PublicFrame>
        <div className="rounded-xl border border-line bg-surface p-10 text-center shadow-soft">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-xl bg-ink-50 text-ink-400">
            <Lock className="h-6 w-6" />
          </div>
          <h1 className="mt-5 text-2xl font-semibold tracking-[-0.03em] text-ink-950">
            {notFound ? 'This trust page is private' : 'Trust page unavailable'}
          </h1>
          <p className="mx-auto mt-2 max-w-sm text-[13px] leading-6 text-ink-500">
            {notFound
              ? 'The merchant has turned off their public trust page. Ask them to share their TrustLayer link again.'
              : 'We could not load this page right now. Please try again in a moment.'}
          </p>
          <Link
            href="/"
            className="mt-6 inline-flex items-center gap-2 rounded-xl bg-navy px-4 py-2.5 text-[12px] font-semibold text-white transition hover:bg-ink-800"
          >
            <ShieldCheck className="h-4 w-4" /> Go to DisputePilot
          </Link>
        </div>
      </PublicFrame>
    );
  }

  const page = query.data;

  return (
    <PublicFrame>
      <div className="overflow-hidden rounded-xl border border-line bg-surface shadow-soft">
        <div className="relative overflow-hidden bg-navy px-6 py-10 text-white sm:px-10 sm:py-12">
          <div className="relative">
            <span
              className={cn(
                'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[10px] font-bold uppercase tracking-[0.1em] ring-1 ring-inset',
                TRUST_TONE[page.state],
              )}
            >
              <BadgeCheck className="h-3.5 w-3.5" />
              TrustLayer {TRUST_LABELS[page.state]}
            </span>
            <h1 className="mt-5 text-balance text-3xl font-semibold leading-tight tracking-[-0.04em] sm:text-[28px]">
              {page.merchant_name}
            </h1>
            <p className="mt-3 max-w-xl text-[14px] leading-7 text-ink-300">
              {page.verification_summary || page.meaning}
            </p>
            <div className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-[12px] text-ink-300">
              <span className="inline-flex items-center gap-1.5">
                <ReceiptText className="h-3.5 w-3.5 text-brand-300" />
                {page.payments_30d} payments reconciled
              </span>
              {page.stable_since ? (
                <span className="inline-flex items-center gap-1.5">
                  <CalendarDays className="h-3.5 w-3.5 text-brand-300" />
                  {TRUST_LABELS[page.state]} since {formatDate(page.stable_since)}
                </span>
              ) : null}
            </div>
          </div>
        </div>

        <div className="px-6 py-8 sm:px-10 sm:py-10">
          <div className="flex items-start gap-3 rounded-xl border border-brand-200 bg-brand-50/60 p-4">
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
            <div>
              <p className="text-[13px] font-semibold text-ink-900">
                Independently verified behaviour
              </p>
              <p className="mt-1 text-[12px] leading-6 text-ink-600">
                This merchant&apos;s trust state is calculated from their operational records on
                DisputePilot — during a minimum {page.window_days}-day window with a minimum sample
                of payments. It is not a review, rating or testimonial.
              </p>
            </div>
          </div>

          <h2 className="mt-8 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-400">
            What this merchant does well
          </h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            {CHECKS.map((check) => (
              <div key={check.title} className="rounded-xl border border-line bg-canvas p-4">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-surface text-brand-700 shadow-sm ring-1 ring-inset ring-line">
                  <check.icon className="h-4 w-4" />
                </div>
                <p className="mt-3 text-[12px] font-semibold text-ink-900">{check.title}</p>
                <p className="mt-1 text-[11px] leading-5 text-ink-500">{check.description}</p>
              </div>
            ))}
          </div>

          <div className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
            <p className="text-[11px] text-ink-400">
              {page.updated_at
                ? `Last updated ${timeAgo(page.updated_at)}`
                : 'Updated automatically'}
            </p>
            <p className="inline-flex items-center gap-1.5 text-[11px] text-ink-400">
              <Lock className="h-3 w-3" /> No customer data or dispute details are exposed
            </p>
          </div>
        </div>
      </div>

      <p className="mt-5 text-center text-[11px] text-ink-400">
        Trust state computed by{' '}
        <Link href="/" className="font-semibold text-ink-600 hover:text-ink-900">
          DisputePilot TrustLayer
        </Link>
      </p>
    </PublicFrame>
  );
}

function PublicFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas">
      <header className="border-b border-line bg-warm-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-6 sm:px-6">
          <Brand />
          <span className="inline-flex items-center gap-1.5 rounded-full bg-surface px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-500 ring-1 ring-inset ring-line">
            <ShieldCheck className="h-3 w-3 text-brand-600" /> TrustLayer
          </span>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-12">{children}</main>
    </div>
  );
}
