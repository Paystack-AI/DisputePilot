import { ShieldCheck } from 'lucide-react';
import { cn } from '@/lib/cn';

export function Brand({
  light = false,
  compact = false,
  className,
}: {
  light?: boolean;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      <div className="relative flex h-9 w-9 items-center justify-center rounded-xl bg-brand-500 text-white shadow-[0_8px_20px_-8px_rgba(32,164,108,0.8)]">
        <ShieldCheck className="h-5 w-5" strokeWidth={2.2} />
        <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-brand-500 bg-amber-300" />
      </div>
      {!compact ? (
        <div>
          <p
            className={cn(
              'text-[15px] font-semibold leading-5 tracking-[-0.03em]',
              light ? 'text-white' : 'text-ink-950',
            )}
          >
            DisputePilot
          </p>
          <p
            className={cn(
              'text-[10px] font-semibold uppercase tracking-[0.18em]',
              light ? 'text-brand-300' : 'text-brand-700',
            )}
          >
            TrustLayer
          </p>
        </div>
      ) : null}
    </div>
  );
}
