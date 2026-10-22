import { forwardRef } from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/cn';

type Variant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger' | 'dark';
type Size = 'sm' | 'md' | 'lg' | 'icon';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

const variants: Record<Variant, string> = {
  // hovers darken with a filter, so they hold in both themes
  primary:
    'bg-brand-600 text-white hover:brightness-[0.93] active:brightness-90 disabled:opacity-50 disabled:hover:brightness-100',
  secondary:
    'bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200 hover:bg-brand-100 disabled:opacity-50',
  outline:
    'bg-surface text-ink-700 ring-1 ring-inset ring-line hover:bg-ink-50 hover:text-ink-900 disabled:opacity-50',
  ghost: 'text-ink-600 hover:bg-ink-100 hover:text-ink-900 disabled:opacity-50',
  danger: 'bg-red-600 text-white hover:brightness-[0.93] disabled:opacity-50 dark:bg-red-500',
  dark: 'bg-navy text-white hover:brightness-125 disabled:opacity-50',
};

const sizes: Record<Size, string> = {
  sm: 'h-8 rounded-md px-3 text-[13px] gap-1.5',
  md: 'h-9 rounded-lg px-3.5 text-[13px] gap-2',
  lg: 'h-11 rounded-lg px-5 text-sm gap-2',
  icon: 'h-9 w-9 rounded-lg',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = 'primary', size = 'md', loading, children, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        'inline-flex items-center justify-center whitespace-nowrap font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed',
        variants[variant],
        sizes[size],
        className,
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
      {children}
    </button>
  );
});
