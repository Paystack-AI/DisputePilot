import { cn } from '@/lib/cn';
import { initials } from '@/lib/format';

export function Avatar({
  name,
  size = 'md',
  className,
}: {
  name: string | null | undefined;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-100 to-brand-200 font-semibold text-brand-800 ring-1 ring-inset ring-brand-200',
        size === 'sm' && 'h-8 w-8 text-[10px]',
        size === 'md' && 'h-10 w-10 text-xs',
        size === 'lg' && 'h-14 w-14 text-base',
        className,
      )}
    >
      {initials(name)}
    </div>
  );
}
