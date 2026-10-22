import Image from 'next/image';
import { cn } from '@/lib/cn';

/** The shield mark and the product name. light: on the navy sidebar or auth panel */
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
      <Image src="/logo.png" alt="DisputePilot" width={30} height={30} priority />
      {!compact ? (
        <span
          className={cn(
            'text-[15px] font-semibold tracking-[-0.02em]',
            light ? 'text-white' : 'text-ink-900',
          )}
        >
          DisputePilot
        </span>
      ) : null}
    </div>
  );
}
