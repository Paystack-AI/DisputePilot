import { cn } from '@/lib/cn';

export function Progress({
  value,
  max = 100,
  tone = 'brand',
  className,
}: {
  value: number | null | undefined;
  max?: number;
  tone?: 'brand' | 'amber' | 'red' | 'ink';
  className?: string;
}) {
  const width = Math.max(0, Math.min(100, ((value ?? 0) / max) * 100));
  const colors = {
    brand: 'bg-brand-500',
    amber: 'bg-amber-500',
    red: 'bg-danger',
    ink: 'bg-ink-800',
  };
  return (
    <div className={cn('h-2 overflow-hidden rounded-full bg-ink-100', className)}>
      <div
        className={cn('h-full rounded-full transition-all duration-500', colors[tone])}
        style={{ width: `${width}%` }}
      />
    </div>
  );
}
