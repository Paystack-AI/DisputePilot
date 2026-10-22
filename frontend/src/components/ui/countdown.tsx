'use client';

import { useEffect, useMemo, useState } from 'react';
import { cn } from '@/lib/cn';

/** Milliseconds until dueAt, ticking every second, against the server's clock */
export function useRemaining(dueAt: string, serverTime?: string) {
  const [now, setNow] = useState(() => Date.now());
  const offset = useMemo(
    () => (serverTime ? new Date(serverTime).getTime() - Date.now() : 0),
    [serverTime],
  );

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  return new Date(dueAt).getTime() - (now + offset);
}

/** 06:23:10 under a day, then 2d 04h */
export function clockLabel(ms: number) {
  if (ms <= 0) return 'Expired';
  const totalSeconds = Math.floor(ms / 1000);
  const days = Math.floor(totalSeconds / 86_400);
  const hours = Math.floor((totalSeconds % 86_400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (days > 0) return `${days}d ${String(hours).padStart(2, '0')}h`;
  return [hours, minutes, seconds].map((part) => String(part).padStart(2, '0')).join(':');
}

/** critical under 4h, warning under 8h, as the api's urgency */
export function urgencyOf(ms: number): 'critical' | 'warning' | 'safe' {
  if (ms < 4 * 3_600_000) return 'critical';
  if (ms < 8 * 3_600_000) return 'warning';
  return 'safe';
}

export function Countdown({
  dueAt,
  serverTime,
  compact = false,
  className,
}: {
  dueAt: string;
  serverTime?: string;
  compact?: boolean;
  className?: string;
}) {
  const remaining = useRemaining(dueAt, serverTime);
  const urgency = urgencyOf(remaining);

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 font-semibold tabular-nums',
        compact ? 'text-[11px]' : 'text-[12px]',
        remaining <= 0
          ? 'bg-ink-100 text-ink-500'
          : urgency === 'critical'
            ? 'bg-red-600 text-white dark:bg-red-500'
            : urgency === 'warning'
              ? 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200'
              : 'bg-ink-100 text-ink-700',
        className,
      )}
      title="Time left to respond"
    >
      {remaining > 0 && urgency === 'critical' ? (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" />
      ) : null}
      {clockLabel(remaining)}
    </span>
  );
}
