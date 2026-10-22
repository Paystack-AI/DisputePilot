import Link from 'next/link';
import { ArrowDownRight, ArrowUpRight } from 'lucide-react';
import { cn } from '@/lib/cn';

const iconTones = {
  default: 'bg-ink-100 text-ink-500',
  brand: 'bg-brand-50 text-brand-600',
  danger: 'bg-red-50 text-red-600',
  amber: 'bg-amber-50 text-amber-600',
  success: 'bg-emerald-50 text-emerald-600',
};

/** A headline number. With href, the whole card opens the list behind the number */
export function StatCard({
  label,
  value,
  detail,
  icon,
  delta,
  tone = 'default',
  href,
  className,
}: {
  label: string;
  value: React.ReactNode;
  detail?: React.ReactNode;
  icon?: React.ReactNode;
  delta?: number | null;
  tone?: keyof typeof iconTones;
  href?: string;
  className?: string;
}) {
  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <p className="text-[12px] text-ink-500">{label}</p>
        {icon ? (
          <span
            className={cn(
              'flex h-7 w-7 items-center justify-center rounded-md [&_svg]:h-3.5 [&_svg]:w-3.5',
              iconTones[tone],
            )}
          >
            {icon}
          </span>
        ) : null}
      </div>
      <p className="mt-2 text-[26px] font-semibold leading-none tracking-[-0.02em] text-ink-950 tabular-nums">
        {value}
      </p>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-2 text-[12px]">
        {delta !== undefined && delta !== null ? (
          <span
            className={cn(
              'inline-flex items-center gap-0.5 font-medium',
              delta >= 0 ? 'text-emerald-600' : 'text-red-600',
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
        {detail ? <span className="text-ink-500">{detail}</span> : null}
      </div>
    </>
  );

  const classes = cn('surface block p-4', href && 'transition hover:border-ink-300', className);
  return href ? (
    <Link href={href} className={classes}>
      {body}
    </Link>
  ) : (
    <div className={classes}>{body}</div>
  );
}
