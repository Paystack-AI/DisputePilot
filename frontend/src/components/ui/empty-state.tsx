import { cn } from '@/lib/cn';

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center rounded-2xl border border-dashed border-ink-200 bg-white/60 px-6 py-14 text-center',
        className,
      )}
    >
      {icon ? (
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-ink-100 text-ink-500">
          {icon}
        </div>
      ) : null}
      <h3 className="text-[15px] font-semibold text-ink-900">{title}</h3>
      {description ? (
        <p className="mt-1.5 max-w-md text-[13px] leading-6 text-ink-500">{description}</p>
      ) : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
