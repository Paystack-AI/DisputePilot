'use client';

import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { BadgeCheck, ShieldCheck } from 'lucide-react';
import { ApiError, apiRequest } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDate } from '@/lib/format';
import { TRUST_LABELS } from '@/lib/constants';
import type { PublicTrustBadge } from '@/lib/types';

export default function PublicTrustBadgePage() {
  const params = useParams<{ token: string }>();
  const token = params?.token;
  const query = useQuery({
    queryKey: ['public-trust-badge', token],
    queryFn: () => apiRequest<PublicTrustBadge>(`/public/trust/${token}/badge`),
    enabled: Boolean(token),
    retry: false,
  });

  if (query.isLoading) {
    return (
      <BadgeFrame>
        <div className="h-[60px] w-[200px] animate-pulse rounded-xl bg-ink-100" />
      </BadgeFrame>
    );
  }

  if (query.isError || !query.data) {
    const hidden = query.error instanceof ApiError && query.error.status === 404;
    return (
      <BadgeFrame>
        <div className="flex h-[60px] w-[200px] items-center gap-2 rounded-xl border border-line bg-surface px-3 text-[10px] text-ink-400">
          <ShieldCheck className="h-4 w-4" />
          {hidden ? 'Badge unavailable' : 'TrustLayer'}
        </div>
      </BadgeFrame>
    );
  }

  const badge = query.data;
  const verified = badge.state === 'verified';

  return (
    <BadgeFrame>
      <div
        className={cn(
          'flex h-[60px] w-[200px] items-center gap-2.5 rounded-xl border px-3',
          verified
            ? 'border-brand-200 bg-brand-50 text-brand-900'
            : 'border-line bg-surface text-ink-900',
        )}
      >
        <span
          className={cn(
            'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
            verified ? 'bg-brand-600 text-white' : 'bg-ink-100 text-ink-500',
          )}
        >
          {verified ? <BadgeCheck className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
        </span>
        <div className="min-w-0">
          <p className="truncate text-[11px] font-semibold leading-4">{badge.merchant_name}</p>
          <p
            className={cn(
              'text-[9px] font-semibold uppercase leading-3 tracking-[0.08em]',
              verified ? 'text-brand-700' : 'text-ink-400',
            )}
          >
            TrustLayer {TRUST_LABELS[badge.state]}
          </p>
          {badge.verified_since ? (
            <p className="mt-0.5 truncate text-[8px] leading-3 text-ink-400">
              Since {formatDate(badge.verified_since)}
            </p>
          ) : null}
        </div>
      </div>
    </BadgeFrame>
  );
}

function BadgeFrame({ children }: { children: React.ReactNode }) {
  return (
    <>
      <style jsx global>{`
        html,
        body {
          background: transparent !important;
          overflow: hidden;
        }
      `}</style>
      {children}
    </>
  );
}
