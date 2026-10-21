import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react';
import { cn } from '@/lib/cn';

type Tone = 'info' | 'success' | 'warning' | 'danger';

const config = {
  info: { icon: Info, styles: 'border-sky-200 bg-sky-50 text-sky-800' },
  success: { icon: CheckCircle2, styles: 'border-brand-200 bg-brand-50 text-brand-800' },
  warning: { icon: AlertTriangle, styles: 'border-amber-200 bg-amber-50 text-amber-800' },
  danger: { icon: XCircle, styles: 'border-red-200 bg-red-50 text-red-800' },
};

export function Alert({
  tone = 'info',
  title,
  children,
  action,
  className,
}: {
  tone?: Tone;
  title?: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  const { icon: Icon, styles } = config[tone];
  return (
    <div className={cn('flex items-start gap-3 rounded-2xl border px-4 py-3.5', styles, className)}>
      <Icon className="mt-0.5 h-[18px] w-[18px] shrink-0" />
      <div className="min-w-0 flex-1">
        {title ? <p className="text-[13px] font-semibold">{title}</p> : null}
        {children ? <div className="text-[13px] leading-5 opacity-90">{children}</div> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
