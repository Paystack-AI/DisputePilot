import Link from 'next/link';
import { href } from '@/lib/links';
import { cn } from '@/lib/cn';

// Inline links to a record. They stop the click from reaching a clickable row around them.
const base = 'hover:text-brand-600 hover:underline underline-offset-2';
const stop = (event: React.MouseEvent) => event.stopPropagation();

export function TransactionLink({
  reference,
  className,
}: {
  reference: string;
  className?: string;
}) {
  return (
    <Link
      href={href.transaction(reference)}
      onClick={stop}
      className={cn('font-mono', base, className)}
    >
      {reference}
    </Link>
  );
}

export function OrderLink({
  order,
  className,
}: {
  order: { id: string; order_number: string | null };
  className?: string;
}) {
  return (
    <Link href={href.order(order.id)} onClick={stop} className={cn(base, className)}>
      Order {order.order_number ?? '(no number)'}
    </Link>
  );
}

export function CustomerLink({
  customer,
  fallback = 'Customer',
  className,
}: {
  customer: { id: string; name: string | null; email: string | null } | null | undefined;
  fallback?: string;
  className?: string;
}) {
  if (!customer) return <span className={className}>{fallback}</span>;
  return (
    <Link href={href.customer(customer.id)} onClick={stop} className={cn(base, className)}>
      {customer.name ?? customer.email ?? fallback}
    </Link>
  );
}
