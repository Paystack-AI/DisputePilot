'use client';

import { cn } from '@/lib/cn';

export function Switch({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative h-6 w-11 shrink-0 rounded-full transition disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'bg-brand-600' : 'bg-ink-200',
      )}
    >
      <span
        className={cn(
          'absolute top-1 h-4 w-4 rounded-full bg-white shadow transition',
          checked ? 'left-6' : 'left-1',
        )}
      />
    </button>
  );
}
