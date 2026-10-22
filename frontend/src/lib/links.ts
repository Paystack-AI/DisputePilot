import type { ActivityItem } from './types';

/** Where each kind of record lives, so any mention of one can link to it */
export const href = {
  dispute: (id: string) => `/disputes/${id}`,
  order: (id: string) => `/orders/${id}`,
  customer: (id: string) => `/customers/${id}`,
  transaction: (reference: string) => `/transactions/${encodeURIComponent(reference)}`,
  fulfillment: (id: string) => `/fulfillments/${id}`,
  session: (id: string) => `/reconciliation/session/${id}`,
  logFulfillment: (orderId: string) => `/fulfillments/new?order=${orderId}`,
};

export function activityHref(item: ActivityItem): string | null {
  const { type, id } = item.link;
  if (type === 'trust') return '/trust';
  if (!id) return null;
  if (type === 'dispute') return href.dispute(id);
  if (type === 'order') return href.order(id);
  if (type === 'reconciliation_session') return href.session(id);
  return null;
}

/**
 * A table row that opens a record when clicked anywhere, except on a link, button or field
 * inside it, which keep their own action.
 */
export function rowClick(go: (url: string) => void, url: string) {
  return (event: React.MouseEvent) => {
    const target = event.target as HTMLElement;
    if (target.closest('a, button, input, select, textarea, label')) return;
    if (window.getSelection()?.toString()) return; // selecting text, not opening
    go(url);
  };
}
