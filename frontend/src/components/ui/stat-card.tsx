import { ArrowDownRight, ArrowUpRight } from 'lucide-react';
import { cn } from '@/lib/cn';

export function StatCard({
  label,
  value,
  detail,
  icon,
  delta,
  tone = 'default',
  className,
}: {
  label: string;
  value: React.ReactNode;
  detail?: React.ReactNode;
  icon?: React.ReactNode;
  delta?: number | null;
  tone?: 'default' | 'danger' | 'brand' | 'amber';
  className?: string;
}) {
  return (
    <div
      className={cn(
        'surface group relative overflow-hidden p-5 transition hover:-translate-y-0.5 hover:shadow-float',
        tone === 'danger' && 'border-red-200 bg-gradient-to-br from-white to-red-50/50',
        tone === 'brand' && 'border-brand-200 bg-gradient-to-br from-white to-brand-50/60',
        tone === 'amber' && 'border-amber-200 bg-gradient-to-br from-white to-amber-50/60',
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[12px] font-semibold uppercase tracking-[0.08em] text-ink-500">
          {label}
        </p>
        {icon ? (
          <div
            className={cn(
              'flex h-9 w-9 items-center justify-center rounded-xl bg-ink-100 text-ink-500',
              tone === 'danger' && 'bg-red-100 text-red-600',
              tone === 'brand' && 'bg-brand-100 text-brand-700',
              tone === 'amber' && 'bg-amber-100 text-amber-700',
            )}
          >
            {icon}
          </div>
        ) : null}
      </div>
      <div className="mt-4 flex items-end gap-2">
        <span className="text-[30px] font-semibold leading-none tracking-[-0.04em] text-ink-950">
          {value}
        </span>
        {delta !== undefined && delta !== null ? (
          <span
            className={cn(
              'mb-0.5 inline-flex items-center gap-0.5 text-[12px] font-semibold',
              delta >= 0 ? 'text-brand-700' : 'text-danger',
            )}
          >
            {delta >= 0 ? (
              <ArrowUpRight className="h-3.5 w-3.5" />
            ) : (
              <ArrowDownRight className="h-3.5 w-3.5" />
            )}
            {Math.abs(delta).toFixed(1)}%
          </span>
        ) : null}
      </div>
      {detail ? <div className="mt-2 text-[12px] leading-5 text-ink-500">{detail}</div> : null}
    </div>
  );
}
