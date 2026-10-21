export type UUID = string;

export type Currency = 'NGN' | 'USD' | 'GHS' | 'ZAR' | 'KES' | 'XOF';
export type OrderStatus = 'pending' | 'paid' | 'fulfilled' | 'cancelled';
export type OrderSource = 'website' | 'whatsapp' | 'instagram' | 'in_store' | 'other';
export type OrderResolution = 'cash_payment' | 'payment_failed';
export type ReconciliationStatus = 'unmatched' | 'auto_matched' | 'manually_matched' | 'flagged';
export type TransactionStatus =
  | 'failed'
  | 'queued'
  | 'pending'
  | 'ongoing'
  | 'success'
  | 'rejected'
  | 'reversed'
  | 'initiated'
  | 'abandoned'
  | 'processing';
export type TransactionChannel =
  | 'card'
  | 'bank'
  | 'bank_transfer'
  | 'mobile_money'
  | 'ussd'
  | 'qr'
  | 'eft'
  | 'apple_pay'
  | 'other';
export type FulfillmentType =
  'delivery' | 'service_completed' | 'digital_download' | 'in_store_pickup';
export type DisputeCategory =
  'chargeback_no_value' | 'chargeback_not_as_described' | 'fraud' | 'admin_error' | 'unknown';
export type DisputeStatus =
  'pending' | 'evidence_generated' | 'submitted' | 'won' | 'lost' | 'auto_accepted';
export type EvidenceState = 'generating' | 'ready';
export type EvidenceStep = 'classify' | 'generate' | 'score';
export type SubmissionState = 'submitting' | 'accepting' | 'submitted' | 'accepted' | 'failed';
export type SubmissionFlow = 'chargeback_flow' | 'fraud_flow';
export type GenerationSource = 'ai' | 'template';
export type DisputeUrgency = 'critical' | 'warning' | 'safe';
export type QualityLabel = 'strong' | 'moderate' | 'weak';
export type ReadinessLabel = 'well_defended' | 'moderate' | 'vulnerable';
export type DisputeAction =
  'generate_evidence' | 'edit_evidence' | 'submit' | 'accept' | 'download_pdf';
export type TrustState = 'verified' | 'building' | 'new' | 'review';
export type ReconciliationSessionStatus = 'in_progress' | 'completed';
export type OnboardingStep =
  | 'connect_paystack'
  | 'configure_notifications'
  | 'initial_sync'
  | 'first_reconciliation'
  | 'completed';
export type InitialSyncStatus = 'not_started' | 'in_progress' | 'completed' | 'failed';
export type PaystackMode = 'live' | 'test';

export interface PageMeta {
  page: number;
  limit: number;
  total: number;
  total_pages: number;
  server_time?: string;
}

export interface Token {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface AdminToken {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface PaystackConnection {
  connected: boolean;
  integration_id: string | null;
  mode: PaystackMode | null;
  connected_at: string | null;
}

export interface Merchant {
  id: UUID;
  email: string | null;
  google_email: string | null;
  business_name: string;
  paystack: PaystackConnection;
  timezone: string;
  default_currency: Currency;
  onboarding: {
    completed: boolean;
    next_step: OnboardingStep;
  };
  created_at: string;
}

export interface Settings {
  notification_email: boolean;
  auto_reconciliation_tier1: boolean;
  default_reconciliation_range: number;
  trust_public_enabled: boolean;
  trust_widget_enabled: boolean;
  timezone: string;
  default_currency: Currency;
  updated_at: string | null;
}

export interface Onboarding {
  next_step: OnboardingStep;
  completed: boolean;
  initial_sync_status: InitialSyncStatus;
  initial_sync_total: number | null;
  initial_sync_processed: number;
  first_reconciliation_skipped: boolean;
  completed_at: string | null;
}

export interface CustomerRef {
  id: UUID;
  name: string | null;
  email: string | null;
  is_shared: boolean;
}

export interface Readiness {
  score: number;
  label: ReadinessLabel;
}

export interface ReadinessComponent {
  key: string;
  label: string;
  status: 'available' | 'missing';
  points: number;
  max_points: number;
  suggestion: string | null;
}

export interface ReadinessDetail extends Readiness {
  components: ReadinessComponent[];
}

export interface TransactionSummary {
  id: UUID;
  reference: string;
  paystack_transaction_id: string;
  amount: number;
  currency: Currency;
  channel: TransactionChannel;
  status: TransactionStatus;
  paid_at: string | null;
  customer_email: string | null;
  order_id: UUID | null;
  reconciliation_status: ReconciliationStatus;
  reconciled_at: string | null;
}

export interface Transaction extends TransactionSummary {
  customer: CustomerRef | null;
  order: { id: UUID; order_number: string | null } | null;
  paystack_fees: number | null;
  customer_name: string | null;
  created_at: string;
  flag_reason: string | null;
  flagged_at: string | null;
  synced_at: string;
  readiness: Readiness | null;
}

export interface TransactionDetail extends Transaction {
  order: {
    id: UUID;
    order_number: string | null;
    description: string | null;
    amount: number;
    currency: Currency;
    status: OrderStatus;
    source: OrderSource;
    created_at: string;
  } | null;
  metadata: Record<string, unknown> | null;
  fulfillments: FulfillmentSummary[];
  dispute: {
    id: UUID;
    paystack_dispute_id: string;
    status: DisputeStatus;
    amount: number;
    currency: Currency;
    due_at: string;
    created_at: string;
  } | null;
  readiness: ReadinessDetail | null;
}

export interface Order {
  id: UUID;
  order_number: string | null;
  customer: CustomerRef | null;
  description: string | null;
  amount: number;
  currency: Currency;
  status: OrderStatus;
  source: OrderSource;
  is_linked: boolean;
  resolution: OrderResolution | null;
  flag_reason: string | null;
  flagged_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface OrderDetail extends Order {
  transactions: TransactionSummary[];
  fulfillments: FulfillmentSummary[];
}

export interface CustomerStats {
  payment_count: number;
  reconciled_count: number;
  reconciled_pct: number | null;
  fulfilled_count: number;
  order_count: number;
  dispute_count: number;
  dispute_rate: number | null;
  first_payment_at: string | null;
  last_payment_at: string | null;
}

export interface CustomerSummary {
  id: UUID;
  name: string | null;
  email: string | null;
  phone: string | null;
  is_shared: boolean;
  payment_count: number;
  reconciled_pct: number | null;
  dispute_count: number;
  last_payment_at: string | null;
  first_seen_at: string | null;
  created_at: string;
}

export interface Customer extends CustomerSummary {
  paystack_customer_code: string | null;
  updated_at: string | null;
  stats: CustomerStats;
}

export interface LedgerEntry {
  kind: 'payment' | 'order' | 'dispute' | 'fulfillment';
  occurred_at: string;
  id: UUID;
  reference: string | null;
  amount: number | null;
  currency: Currency | null;
  status: string;
  order_id: UUID | null;
  transaction_id: UUID | null;
}

export interface FileRef {
  id: UUID;
  file_name: string;
  content_type: string;
  size: number;
  width: number;
  height: number;
  created_at: string;
}

export interface FulfillmentSummary {
  id: UUID;
  transaction_id: UUID | null;
  type: FulfillmentType;
  delivery_date: string;
  tracking_number: string | null;
  recipient_name: string | null;
  created_at: string;
}

export interface Fulfillment extends FulfillmentSummary {
  order_id: UUID;
  delivery_address: string | null;
  notes: string | null;
  files: FileRef[];
  updated_at: string | null;
}

export interface DisputeCustomer {
  name: string | null;
  email: string | null;
}

export interface Quality {
  score: number;
  label: QualityLabel;
  dimension_scores: Record<string, number> | null;
  suggestions: string[];
  ready_to_submit: boolean | null;
}

export interface DisputeSummary {
  id: UUID;
  paystack_dispute_id: string;
  status: DisputeStatus;
  paystack_status: string | null;
  category: DisputeCategory | null;
  reason: string | null;
  amount: number;
  currency: Currency;
  created_at: string;
  due_at: string;
  urgency: DisputeUrgency | null;
  customer: DisputeCustomer | null;
  transaction_reference: string;
  readiness: Readiness | null;
  quality: Quality | null;
  evidence_state: EvidenceState | null;
  submission_state: SubmissionState | null;
}

export interface EvidenceDocumentRef {
  file_id: UUID;
  file_name: string;
  caption: string | null;
  source: 'fulfillment' | 'merchant';
}

export interface FulfillmentEvidence {
  type: FulfillmentType;
  delivery_date: string;
  tracking_number: string | null;
  recipient_name: string | null;
  delivery_address: string | null;
  notes: string | null;
  photos: EvidenceDocumentRef[];
}

export interface EvidenceDocument {
  version: number;
  generation_source: GenerationSource | null;
  generated_at: string | null;
  edited_at: string | null;
  header: {
    business_name: string;
    paystack_integration_id: string | null;
    document_date: string;
    dispute_reference: string;
    transaction_reference: string;
  };
  transaction_receipt: {
    paid_at: string | null;
    amount: number;
    currency: Currency;
    channel: TransactionChannel;
    reference: string;
    customer_email: string | null;
    customer_name: string | null;
  };
  order_details: {
    order_number: string | null;
    description: string | null;
    created_at: string;
    amount: number;
    currency: Currency;
  } | null;
  fulfillment_evidence: FulfillmentEvidence[];
  narrative: string | null;
  supporting_documents: EvidenceDocumentRef[];
  customer_history: {
    payment_count: number;
    first_payment_at: string | null;
    prior_disputes: number;
  } | null;
  conclusion: string | null;
  missing_evidence: string[];
  quality: Quality | null;
  editable: string[];
}

export interface DisputeDetail extends DisputeSummary {
  server_time: string;
  category_confidence: number | null;
  submission_flow: SubmissionFlow | null;
  special_instructions: string | null;
  evidence_step: EvidenceStep | null;
  submission_error: string | null;
  submitted_at: string | null;
  resolved_at: string | null;
  allowed_actions: DisputeAction[];
  recommendation: 'accept' | null;
  readiness: ReadinessDetail | null;
  evidence: EvidenceDocument;
  customer: CustomerRef | null;
}

export interface DisputeStats {
  total: number;
  open: number;
  submitted: number;
  won: number;
  lost: number;
  auto_accepted: number;
  win_rate: number | null;
  avg_response_hours: number | null;
}

export interface StatementBlock {
  label: string;
  value: string | number | null;
  detail?: string;
}

export interface ReconciliationTotals {
  total_transactions: number;
  matched: number;
  suggested: number;
  unmatched_payments: number;
  flagged: number;
  unmatched_orders: number;
}

export interface ReconciliationSession {
  id: UUID;
  date_range_start: string;
  date_range_end: string;
  status: ReconciliationSessionStatus;
  totals: ReconciliationTotals;
  completed_at: string | null;
  created_at: string;
}

export interface MatchedItem {
  transaction: Transaction;
  order: Order;
  tier: number | null;
  confidence: number | null;
  accepted_at: string | null;
}

export interface SuggestionItem {
  id: UUID;
  transaction: Transaction;
  order: Order;
  tier: number;
  likelihood_percent: number;
  confidence_tier: 'likely' | 'possible';
  reasoning: string;
}

export interface RankedPayment {
  transaction: Transaction;
  reason: string | null;
}

export interface RankedOrder {
  order: Order;
  reason: string | null;
}

export interface ReconciliationView {
  session: ReconciliationSession;
  matched: MatchedItem[];
  suggestions: SuggestionItem[];
  unmatched_payments: Transaction[];
  unmatched_orders: Order[];
  flagged: RankedPayment[];
  flagged_orders: RankedOrder[];
}

export interface ReconciliationSummary {
  synced_today: number;
  matched_today: number;
  needs_review: number;
  last_completed_at: string | null;
}

export interface TrustSignal {
  key:
    | 'reconciliation_rate'
    | 'fulfillment_rate'
    | 'dispute_rate'
    | 'dispute_win_rate'
    | 'avg_response_time'
    | 'evidence_readiness';
  label: string;
  value: number | null;
  reading: 'strong' | 'fair' | 'weak' | 'insufficient';
  verified_threshold: string | null;
  building_threshold: string | null;
  action: string | null;
}

export interface TrustProfile {
  state: TrustState;
  label: string;
  meaning: string;
  internal_score: number | null;
  signals: TrustSignal[];
  sample: {
    payments_30d: number;
    days_on_platform: number;
    min_sample_met: boolean;
  } | null;
  public_enabled: boolean;
  widget_enabled: boolean;
  public_url: string;
  last_computed_at: string | null;
  stable_since: string | null;
  explanation: string | null;
  explained_at: string | null;
}

export interface TrustSignals {
  state: TrustState;
  next_state: TrustState | null;
  blocking: string[];
  contributing: string[];
  signals: TrustSignal[];
  sample: TrustProfile['sample'];
}

export interface TrustAction {
  action: string;
  impact_description: string;
  affected_signal: string;
}

export interface TrustActions {
  actions: TrustAction[];
  generated_at: string | null;
}

export interface TrustHistory {
  days: number;
  points: {
    at: string;
    state: TrustState;
    internal_score: number | null;
    reason: string;
    signals: Record<string, number | null>;
    summary: string | null;
  }[];
  changes: {
    at: string;
    from_state: TrustState | null;
    to_state: TrustState;
    reason: string;
    summary: string | null;
  }[];
}

export interface PublicTrustPage {
  merchant_name: string;
  state: TrustState;
  label: string;
  meaning: string;
  verification_summary: string;
  payments_30d: number;
  window_days: number;
  updated_at: string | null;
  stable_since: string | null;
}

export interface PublicTrustBadge {
  merchant_name: string;
  state: TrustState;
  label: string;
  verified_since: string | null;
  updated_at: string | null;
}

export interface DashboardPeriod {
  date_from: string;
  date_to: string;
  previous_from: string;
  previous_to: string;
}

export interface ActivityItem {
  type:
    | 'dispute_created'
    | 'dispute_submitted'
    | 'dispute_won'
    | 'dispute_lost'
    | 'dispute_auto_accepted'
    | 'fulfillment_logged'
    | 'reconciliation_completed'
    | 'trust_changed';
  occurred_at: string;
  title: string;
  link: {
    type: 'dispute' | 'order' | 'reconciliation_session' | 'trust';
    id: UUID | null;
  };
}

export interface Dashboard {
  server_time: string;
  currency: Currency;
  period: DashboardPeriod;
  metrics: {
    transactions: { count: number; successful: number; delta_pct: number | null } | null;
    disputes: { open: number; critical: number; opened: number; resolved: number } | null;
    readiness: {
      score: number | null;
      label: ReadinessLabel | null;
      distribution: Record<string, number>;
    } | null;
    reconciliation: {
      matched_pct: number | null;
      unmatched: number;
      delta_pct: number | null;
    } | null;
  };
  critical_dispute: {
    id: UUID;
    paystack_dispute_id: string;
    amount: number;
    currency: Currency;
    due_at: string;
    customer_name: string | null;
  } | null;
  reconciliation: ReconciliationSummary | null;
  trust: { state: TrustState; label: string; updated_at: string | null } | null;
  prompts:
    | {
        type: 'log_fulfillment';
        order_id: UUID;
        order_number: string | null;
        amount: number;
        currency: Currency;
      }[]
    | null;
  recent_transactions: Transaction[] | null;
  recent_disputes: DisputeSummary[] | null;
  activity: ActivityItem[] | null;
}

export interface DisputeTimeline {
  days: number;
  series: {
    date: string;
    opened: number;
    won: number;
    lost: number;
    auto_accepted: number;
  }[];
}

export interface ReconciliationHealth {
  days: number;
  sessions_started: number;
  sessions_completed: number;
  completion_rate: number | null;
  avg_mismatches: number | null;
  series: {
    date: string;
    payments: number;
    matched: number;
    matched_pct: number | null;
  }[];
}

export interface WebhookSettings {
  url: string;
  active: boolean;
  last_received_at: string | null;
  events: string[];
  setup_steps: string[];
}

export interface AdminProfile {
  id: UUID;
  email: string;
  name: string | null;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface AdminOverview {
  total_merchants: number;
  active_merchants: number;
  verified_merchants: number;
  paystack_connected_merchants: number;
  onboarding_completed_merchants: number;
  total_transactions: number;
  successful_transactions: number;
  total_disputes: number;
  open_disputes: number;
  total_orders: number;
  total_customers: number;
  trust_states: Record<string, number>;
}

export interface AdminMerchantListItem {
  id: UUID;
  business_name: string;
  email: string | null;
  is_verified: boolean;
  is_active: boolean;
  paystack_connected: boolean;
  paystack_mode: PaystackMode | null;
  onboarding_step: OnboardingStep | null;
  onboarding_completed: boolean;
  trust_state: TrustState | null;
  transaction_count: number;
  dispute_count: number;
  created_at: string;
}

export interface AdminMerchantDetail {
  id: UUID;
  business_name: string;
  email: string | null;
  google_email: string | null;
  is_verified: boolean;
  is_active: boolean;
  deactivated_at: string | null;
  created_at: string;
  updated_at: string | null;
  paystack: {
    connected: boolean;
    integration_id: string | null;
    mode: PaystackMode | null;
    connected_at: string | null;
    last_transaction_sync_at: string | null;
    webhook_configured: boolean;
    webhook_last_received_at: string | null;
  };
  onboarding: {
    current_step: OnboardingStep;
    initial_sync_status: InitialSyncStatus;
    initial_sync_total: number | null;
    initial_sync_processed: number;
    first_reconciliation_skipped: boolean;
    completed_at: string | null;
  } | null;
  settings: {
    notification_email: boolean;
    auto_reconciliation_tier1: boolean;
    default_reconciliation_range: number;
    trust_public_enabled: boolean;
    trust_widget_enabled: boolean;
    timezone: string;
    default_currency: Currency;
  } | null;
  trust: {
    state: TrustState;
    internal_score: number | null;
    reconciliation_rate: number | null;
    fulfillment_rate: number | null;
    dispute_rate: number | null;
    dispute_win_rate: number | null;
    avg_response_time_pct: number | null;
    evidence_readiness_avg: number | null;
    payments_30d: number | null;
    days_on_platform: number | null;
    explanation: string | null;
    recommendations: Record<string, unknown>[] | null;
    explained_at: string | null;
    last_computed_at: string | null;
  } | null;
  stats: {
    transaction_count: number;
    successful_transactions: number;
    dispute_count: number;
    open_disputes: number;
    order_count: number;
    customer_count: number;
  };
  recent_transactions: {
    id: UUID;
    reference: string;
    paystack_transaction_id: string;
    amount: number;
    currency: Currency;
    channel: TransactionChannel;
    status: TransactionStatus;
    reconciliation_status: ReconciliationStatus;
    customer_email: string | null;
    customer_name: string | null;
    order_id: UUID | null;
    paid_at: string | null;
    created_at: string;
  }[];
  recent_disputes: {
    id: UUID;
    reference: string;
    paystack_dispute_id: string;
    status: DisputeStatus;
    category: DisputeCategory | null;
    amount: number;
    currency: Currency;
    created_at: string;
    due_at: string;
    resolved_at: string | null;
    evidence_state: EvidenceState | null;
    submission_state: SubmissionState | null;
  }[];
  trust_history: {
    id: UUID;
    state: TrustState;
    internal_score: number | null;
    reason: string;
    summary: string | null;
    signals: Record<string, number | null>;
    created_at: string;
  }[];
}

export interface ApiErrorPayload {
  error: {
    code: string;
    message: string;
    request_id: string;
    details?: Record<string, string> | null;
  };
}
