import { cn } from '@/lib/cn';

type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'purple' | 'dark';

const tones: Record<Tone, string> = {
  neutral: 'bg-ink-100 text-ink-600 ring-ink-200',
  success: 'bg-brand-50 text-brand-700 ring-brand-200',
  warning: 'bg-amber-50 text-amber-700 ring-amber-200',
  danger: 'bg-red-50 text-red-700 ring-red-200',
  info: 'bg-sky-50 text-sky-700 ring-sky-200',
  purple: 'bg-violet-50 text-violet-700 ring-violet-200',
  dark: 'bg-ink-900 text-white ring-ink-900',
};

export function Badge({
  tone = 'neutral',
  className,
  children,
  dot,
}: {
  tone?: Tone;
  className?: string;
  children: React.ReactNode;
  dot?: boolean;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset',
        tones[tone],
        className,
      )}
    >
      {dot ? <span className="h-1.5 w-1.5 rounded-full bg-current" /> : null}
      {children}
    </span>
  );
}

export function statusTone(status: string): Tone {
  if (
    [
      'won',
      'success',
      'paid',
      'fulfilled',
      'verified',
      'auto_matched',
      'manually_matched',
    ].includes(status)
  )
    return 'success';
  if (
    ['pending', 'processing', 'ongoing', 'submitted', 'submitting', 'building', 'new'].includes(
      status,
    )
  )
    return 'warning';
  if (['lost', 'failed', 'critical', 'review', 'flagged', 'reversed', 'rejected'].includes(status))
    return 'danger';
  if (['evidence_generated', 'ready', 'accepted'].includes(status)) return 'info';
  return 'neutral';
}
