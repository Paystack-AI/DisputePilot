'use client';

import { useEffect, useMemo, useState } from 'react';
import { Clock3 } from 'lucide-react';
import { cn } from '@/lib/cn';

function remainingLabel(ms: number) {
  if (ms <= 0) return 'Expired';
  const totalMinutes = Math.floor(ms / 60_000);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  const seconds = Math.floor((ms % 60_000) / 1000);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
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
  const [now, setNow] = useState(() => Date.now());
  const offset = useMemo(() => {
    if (!serverTime) return 0;
    return new Date(serverTime).getTime() - Date.now();
  }, [serverTime]);

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  const remaining = new Date(dueAt).getTime() - (now + offset);
  const tone =
    remaining < 3_600_000
      ? 'bg-ink-950 text-white animate-pulse-ring'
      : remaining < 4 * 3_600_000
        ? 'bg-red-50 text-red-700 ring-red-200'
        : remaining < 8 * 3_600_000
          ? 'bg-amber-50 text-amber-700 ring-amber-200'
          : 'bg-brand-50 text-brand-700 ring-brand-200';

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold tabular-nums ring-1 ring-inset',
        tone,
        compact ? '' : 'text-xs',
        className,
      )}
    >
      <Clock3 className="h-3.5 w-3.5" />
      {remainingLabel(remaining)}
    </span>
  );
}
