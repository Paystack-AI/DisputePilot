import type {
  DisputeCategory,
  DisputeStatus,
  FulfillmentType,
  OnboardingStep,
  OrderSource,
  OrderStatus,
  ReconciliationStatus,
  TransactionStatus,
  TrustState,
} from './types';

export const CURRENCIES = ['NGN', 'USD', 'GHS', 'ZAR', 'KES', 'XOF'] as const;
export const ORDER_SOURCES: OrderSource[] = [
  'website',
  'whatsapp',
  'instagram',
  'in_store',
  'other',
];

export const FULFILLMENT_TYPES: { value: FulfillmentType; label: string }[] = [
  { value: 'delivery', label: 'Delivery' },
  { value: 'service_completed', label: 'Service completed' },
  { value: 'digital_download', label: 'Digital download' },
  { value: 'in_store_pickup', label: 'In-store pickup' },
];

export const ORDER_STATUSES: OrderStatus[] = ['pending', 'paid', 'fulfilled', 'cancelled'];
export const DISPUTE_STATUSES: DisputeStatus[] = [
  'pending',
  'evidence_generated',
  'submitted',
  'won',
  'lost',
  'auto_accepted',
];

export const CATEGORY_LABELS: Record<DisputeCategory, string> = {
  chargeback_no_value: 'No value received',
  chargeback_not_as_described: 'Not as described',
  fraud: 'Fraud',
  admin_error: 'Admin error',
  unknown: 'Unclassified',
};

export const STATUS_LABELS: Record<DisputeStatus, string> = {
  pending: 'Pending',
  evidence_generated: 'Evidence ready',
  submitted: 'Submitted',
  won: 'Won',
  lost: 'Lost',
  auto_accepted: 'Auto-accepted',
};

export const ORDER_STATUS_LABELS: Record<OrderStatus, string> = {
  pending: 'Pending',
  paid: 'Paid',
  fulfilled: 'Fulfilled',
  cancelled: 'Cancelled',
};

export const RECONCILIATION_LABELS: Record<ReconciliationStatus, string> = {
  unmatched: 'Unmatched',
  auto_matched: 'Auto-matched',
  manually_matched: 'Manually matched',
  flagged: 'Flagged',
};

export const TRANSACTION_LABELS: Record<TransactionStatus, string> = {
  failed: 'Failed',
  queued: 'Queued',
  pending: 'Pending',
  ongoing: 'Ongoing',
  success: 'Successful',
  rejected: 'Rejected',
  reversed: 'Reversed',
  initiated: 'Initiated',
  abandoned: 'Abandoned',
  processing: 'Processing',
};

export const TRUST_LABELS: Record<TrustState, string> = {
  verified: 'Verified',
  building: 'Building',
  new: 'New',
  review: 'Under review',
};

export const ONBOARDING_LABELS: Record<OnboardingStep, string> = {
  connect_paystack: 'Connect Paystack',
  configure_notifications: 'Notifications',
  initial_sync: 'Importing transactions',
  first_reconciliation: 'First reconciliation',
  completed: 'Complete',
};

export const TRUST_TONE: Record<TrustState, string> = {
  verified: 'bg-brand-50 text-brand-700 ring-brand-200',
  building: 'bg-amber-50 text-amber-700 ring-amber-200',
  new: 'bg-sky-50 text-sky-700 ring-sky-200',
  review: 'bg-red-50 text-red-700 ring-red-200',
};
