export type UserRole = "owner" | "user" | "merchant" | "team_lead";

export interface Account {
  id: string;
  username: string;
  role: UserRole;
  full_name: string;
  email: string | null;
  phone: string | null;
  is_active: boolean;
  is_verified: boolean;
  team_lead_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface LoginInput { username: string; password: string }

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  access_expires_in: number;
}

export interface TwoFactorRequiredResponse {
  two_factor_required: true;
  challenge_token: string;
  expires_in: number;
}

export interface TwoFactorSetupRequiredResponse {
  two_factor_setup_required: true;
  setup_token: string;
  expires_in: number;
}

export interface TwoFactorStatus {
  enabled: boolean;
  required: boolean;
  enabled_at: string | null;
  recovery_codes_remaining: number;
}

export interface TwoFactorSetupStart {
  otpauth_uri: string;
  manual_key: string;
  expires_at: string;
}

export interface TwoFactorSetupConfirmResult {
  enabled_at: string;
  recovery_codes: string[];
  // Populated only when confirming via a forced-onboarding setup_token -
  // no session existed before this call, so one is created here.
  access_token?: string;
  refresh_token?: string;
  access_expires_in?: number;
}

export interface TwoFactorRegenerateResult {
  recovery_codes: string[];
}

export interface AuthSessionInfo {
  id: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  device_name: string | null;
  is_current: boolean;
}

export interface AuthSessionListResponse {
  items: AuthSessionInfo[];
}

export interface LogoutAllResult {
  revoked_count: number;
}

export interface ValidationIssue {
  loc?: Array<string | number>;
  msg?: string;
  type?: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Wallet {
  currency: "USDT" | "usdt";
  available_balance: string;
  insurance_balance: string;
  frozen_balance: string;
}

export interface InsuranceReservePolicy {
  id: string;
  version: number;
  status: string;
  enabled: boolean;
  minimum_reserve_percentage: string;
  created_by_account_id: string | null;
  created_at: string;
  updated_at: string;
  activated_at: string | null;
}

export interface InsuranceReservePolicyInput {
  enabled: boolean;
  minimum_reserve_percentage: string;
}

export interface InsuranceReserveWalletView {
  account_id: string;
  insurance_balance: string;
  insurance_reserve_basis: string;
  minimum_reserve_percentage: string;
  required_minimum_reserve: string;
  available_above_reserve: string;
  policy_version: number;
  policy_enabled: boolean;
  policy_updated_at: string;
}

export interface MerchantWallet {
  currency: "USDT" | "usdt";
  available_balance: string;
  held_balance: string;
}

export type FiatCurrency = "TJS" | "RUB";

export interface FiatBalance {
  currency: FiatCurrency;
  available: string;
  updated_at: string;
}

export interface FiatBalanceList {
  items: FiatBalance[];
}

export interface FiatAllocation {
  operation_id: string;
  account_id: string;
  currency: FiatCurrency;
  amount: string;
  balance_before: string;
  balance_after: string;
  created_at: string;
}

export interface FiatConversionPreview {
  from_currency: FiatCurrency;
  to_currency: FiatCurrency;
  source_amount: string;
  destination_amount: string;
  gross_destination_amount: string;
  fee_amount: string;
  exchange_rate: string;
  reference_rate: string;
  effective_rate: string;
  fee_policy_version: number;
  provider: string;
  published_at: string;
  received_at: string;
  provider_nominal: string;
  provider_rate: string;
  policy_version: string;
  mode: string;
  is_stale: boolean;
}

export interface FiatConversion {
  id: string;
  account_id: string;
  initiated_by_account_id: string;
  from_currency: FiatCurrency;
  to_currency: FiatCurrency;
  source_amount: string;
  destination_amount: string;
  gross_destination_amount: string;
  fee_amount: string;
  exchange_rate: string;
  reference_rate: string;
  effective_rate: string;
  fee_policy_version: number;
  source_balance_before: string;
  source_balance_after: string;
  destination_balance_before: string;
  destination_balance_after: string;
  rate_provider: string;
  rate_published_at: string;
  rate_policy_version: string;
  rate_mode: string;
  comment: string | null;
  created_at: string;
}

export type FeeType = "deal_fee" | "fiat_conversion_spread" | "withdrawal_fee" | "merchant_fee";
export interface FeeComponent {
  fee_type: FeeType;
  enabled: boolean;
  percent_bps: number;
  fixed_fee: string;
  min_fee: string | null;
  max_fee: string | null;
  payer: "USER" | "MERCHANT" | null;
  supported_for_charging: boolean;
}
export interface FeePolicy {
  id: string;
  version: number;
  status: "draft" | "active" | "retired";
  effective_from: string | null;
  created_at: string;
  activated_at: string | null;
  components: FeeComponent[];
}
export interface FeePreview {
  policy_version: number;
  fee_type: FeeType;
  currency: FiatCurrency | "USDT";
  gross: string;
  percent_fee: string;
  fixed_fee: string;
  total_fee: string;
  net: string;
}
export interface ProfitMetric {
  currency: FiatCurrency | "USDT";
  fee_type: FeeType;
  gross_volume: string;
  total_fees: string;
  transaction_count: number;
  average_fee: string;
}
export interface ProfitSummary { periods: Record<"today" | "7d" | "30d" | "all", ProfitMetric[]>; }
export interface ProfitEntry {
  id: string;
  source_type: string;
  source_id: string;
  fee_type: FeeType;
  currency: FiatCurrency | "USDT";
  gross_amount: string;
  fee_amount: string;
  policy_version: number;
  created_at: string;
}

export interface FiatLedgerEntry {
  id: string;
  currency: FiatCurrency;
  type: "owner_allocation" | "conversion_debit" | "conversion_credit";
  amount: string;
  balance_before: string;
  balance_after: string;
  reference_type: string;
  reference_id: string;
  description: string | null;
  created_by_account_id: string;
  created_at: string;
}

export interface LedgerEntry {
  id: string;
  type: string;
  balance_bucket: string;
  currency: string;
  amount: string;
  available_before: string;
  available_after: string;
  insurance_before: string;
  insurance_after: string;
  frozen_before: string;
  frozen_after: string;
  held_before: string;
  held_after: string;
  reference_type: string | null;
  reference_id: string | null;
  description: string | null;
  created_by_account_id: string | null;
  created_at: string;
}

export interface PaymentRequisite {
  id: string;
  type: "bank_card";
  bank_name: string;
  holder_name: string;
  phone_number: string | null;
  masked_card_number: string;
  is_active: boolean;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface TrafficSettings {
  is_enabled: boolean;
  enabled_at: string | null;
  disabled_at: string | null;
}

export interface UserWithdrawal {
  id: string;
  public_id: string;
  user_id: string;
  wallet_id: string;
  amount: string;
  currency: string;
  destination_type: "usdt_trc20_address" | "bybit_uid";
  destination: string;
  status: "pending" | "approved" | "paid" | "rejected" | "cancelled";
  comment: string | null;
  owner_comment: string | null;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
  rejected_at: string | null;
  paid_at: string | null;
  cancelled_at: string | null;
}

export interface MerchantWithdrawal {
  id: string;
  public_id: string;
  merchant_id: string;
  merchant_wallet_id: string;
  amount: string;
  currency: string;
  destination_type: "usdt_trc20_address" | "bybit_uid";
  destination: string;
  status: "pending" | "approved" | "paid" | "rejected" | "cancelled";
  comment: string | null;
  owner_comment: string | null;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
  rejected_at: string | null;
  paid_at: string | null;
  cancelled_at: string | null;
}

export type DealStatus = "created" | "available" | "accepted" | "payment_pending" | "completed" | "cancelled" | "expired" | "disputed";

export interface Deal {
  id: string;
  public_id: string;
  merchant_id: string;
  user_id: string | null;
  payment_requisite_id: string | null;
  status: DealStatus;
  amount_tjs: string;
  exchange_rate: string | null;
  amount_usdt: string | null;
  requisite_type: "bank_card" | null;
  requisite_bank_name: string | null;
  requisite_holder_name: string | null;
  requisite_masked_card_number: string | null;
  expires_at: string;
  accepted_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  created_at: string;
  updated_at: string;
  merchant_settlement_amount: string | null;
  user_profit_amount: string | null;
  /** Only present in the OWNER view (GET /owner/deals/*) - the platform's
   * own retained margin, never sent to USER/MERCHANT responses. */
  owner_profit_amount?: string | null;
  /** Present in the OWNER view and the TEAM_LEAD's own view of their
   * team's deals (GET /team-lead/deals) - never sent to USER/MERCHANT. */
  team_lead_profit_amount?: string | null;
}

export interface TeamMember {
  id: string;
  username: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
}

export interface TeamLeadDashboard {
  profit_available: string;
  profit_pending_withdrawal: string;
  team_size: number;
  deal_count: number;
  deal_volume: string;
}

export type WithdrawalStatus = "pending" | "approved" | "paid" | "rejected" | "cancelled";
export type WithdrawalDestinationType = "usdt_trc20_address" | "bybit_uid";

export interface TeamLeadWithdrawal {
  id: string;
  public_id: string;
  team_lead_id: string;
  wallet_id: string;
  amount: string;
  currency: string;
  destination_type: WithdrawalDestinationType;
  destination: string;
  status: WithdrawalStatus;
  comment: string | null;
  owner_comment: string | null;
  created_at: string;
  updated_at: string;
  approved_at: string | null;
  rejected_at: string | null;
  paid_at: string | null;
  cancelled_at: string | null;
  created_by_account_id: string;
  actioned_by_account_id: string | null;
}

export type AppealStatus = "open" | "under_review" | "resolved" | "cancelled";
export type AppealReason = "payment_not_received" | "wrong_amount" | "payment_proof_issue" | "timeout_dispute" | "other";
export interface Appeal {
  id: string;
  public_id: string;
  deal_id: string;
  opened_by_account_id: string;
  opened_by_role: UserRole;
  reason_code: AppealReason;
  message: string;
  status: AppealStatus;
  resolution: "settle_to_merchant" | "release_to_user" | null;
  owner_note: string | null;
  previous_deal_status: DealStatus;
  resolved_by_account_id: string | null;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
}

export interface NotificationItem {
  id: string;
  account_id: string;
  type: string;
  title: string;
  message: string;
  message_key: string | null;
  message_params: Record<string, string | number | boolean | null> | null;
  payload: Record<string, unknown> | null;
  is_read: boolean;
  created_at: string;
}

export type NotificationDeliveryStatus = "PENDING" | "SENT" | "FAILED";

export interface NotificationDelivery {
  id: string;
  notification_id: string;
  channel: "TELEGRAM" | "IN_APP";
  status: NotificationDeliveryStatus;
  attempts: number;
  last_error: string | null;
  sent_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface NotificationPreferences {
  account_id: string;
  in_app_enabled: boolean;
  telegram_enabled: boolean;
  deal_notifications: boolean;
  deposit_notifications: boolean;
  appeal_notifications: boolean;
  withdrawal_notifications: boolean;
}

export interface TelegramLinkToken {
  deep_link: string;
  expires_at: string;
  bot_username: string;
}

export interface TelegramConnection {
  connected: boolean;
  masked_username: string | null;
  linked_at: string | null;
  language: "ru" | "en" | "tg";
  delivery_enabled: boolean;
  unhealthy_reason: string | null;
}

export interface IntegrationDiagnostics {
  status: string;
  environment: string;
  providers: {
    deposit_provider: string;
    exchange_rate_provider: string;
    payout_provider: string;
  };
  safety: {
    payout_enabled: boolean;
    trading_enabled: boolean;
    usdt_contract_address: string;
    required_confirmations: number;
  };
  market_data: {
    primary: "binance" | "bybit";
    secondary: "binance" | "bybit";
    active_provider: "binance" | "bybit" | null;
    status: "connected" | "degraded" | "unavailable";
    cache: "redis" | "direct" | "unavailable";
    symbol: string;
    deviation_bps: string | null;
    providers: Record<"binance" | "bybit", MarketProviderDiagnostic>;
  };
  fiat_rate: {
    status: "connected" | "degraded" | "unavailable";
    primary: string;
    secondary: string;
    active_provider: string | null;
    cache: "redis" | "direct" | "unavailable";
    max_age_seconds: number;
    deviation_bps: string | null;
    providers: Record<string, FiatProviderDiagnostic>;
  };
  business_rate: {
    status: "connected" | "degraded" | "unavailable";
    rate_tjs_per_usdt: string | null;
    fiat_rate_tjs_per_usd?: string;
    usdt_usd_rate?: string;
    fiat_provider: string | null;
    market_provider: string | null;
    peg_mode: string;
    policy_version: string;
    calculated_at: string | null;
    is_degraded: boolean;
  };
  exchange_private: {
    binance: {
      configured: boolean;
      enabled: boolean;
      status: string;
      mode: "READ_ONLY";
      reason: string;
    };
    bybit: ExchangePrivateDiagnostic;
  };
}

export interface ExchangePrivateDiagnostic {
  provider: "bybit";
  configured: boolean;
  enabled: boolean;
  status: string;
  authentication: string;
  mode: "READ_ONLY";
  permission_safety: "READ_ONLY_SAFE" | "OVER_PRIVILEGED" | "UNKNOWN";
  masked_key: string | null;
  ip_restricted: boolean | null;
  expires_at: string | null;
  deadline_days: number | null;
  account: {
    provider: "bybit";
    account_type: string;
    account_mode: string;
    margin_mode: string;
    account_status: string;
    updated_at: string | null;
  } | null;
  balances: Array<{
    provider: "bybit";
    asset: "USDT" | "USDC";
    wallet_balance: string;
    available_balance: string | null;
    equity: string | null;
    received_at: string;
  }>;
  latency_ms: number | null;
  last_success_at: string | null;
  rate_limit_remaining: number | null;
}

export interface FiatProviderDiagnostic {
  status: "connected" | "degraded" | "unavailable" | "stale";
  source_type: "official" | "indicative_fx";
  pair: string;
  rate: string | null;
  published_at: string | null;
  received_at: string | null;
  latency_ms: number | null;
  cached: boolean;
  role: "primary" | "secondary";
  business_fallback_allowed: boolean;
}

export interface MarketProviderDiagnostic {
  status: "connected" | "degraded" | "unavailable";
  public_api: boolean;
  read_only: boolean;
  base_url: string;
  latency_ms: number | null;
  last_success_at: string | null;
  role: "primary" | "fallback";
  circuit: "open" | "closed";
}

export interface AuditLogEntry {
  id: string;
  actor_account_id: string | null;
  actor_role: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  request_id: string | null;
  created_at: string;
}

export type CorrelationStatus = "MATCHED" | "AMBIGUOUS" | "UNMATCHED";
export type ReconciliationStatus = "PENDING" | "LINKED" | "REPROCESSED" | "IGNORED" | "CREDITED" | "FAILED";
export interface UnmatchedTransfer {
  id: string;
  tx_hash: string;
  provider_event_id: string;
  provider: string;
  from_address: string;
  to_address: string;
  amount: string;
  asset_contract: string;
  network: string;
  confirmations: number;
  is_finalized: boolean;
  block_number: number | null;
  block_timestamp: string | null;
  correlation_status: CorrelationStatus;
  reconciliation_status: ReconciliationStatus;
  reason: string;
  linked_deposit_id: string | null;
  resolution_reason: string | null;
  last_result_code: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DepositCandidate {
  id: string;
  public_id: string;
  account_id: string;
  expected_amount: string;
  network: string;
  asset: string;
  status: DepositStatus;
  expires_at: string;
  amount_matches: boolean;
  amount_difference: string;
}

export interface DepositReconciliationAction {
  id: string;
  action: "LINK" | "REPROCESS" | "IGNORE";
  deposit_id: string | null;
  result_code: string;
  created_at: string;
}

export interface UnmatchedTransferDetail extends UnmatchedTransfer {
  candidates: DepositCandidate[];
  history: DepositReconciliationAction[];
}

export interface DepositReconciliationResult {
  result_code: string;
  replayed: boolean;
  transfer: UnmatchedTransfer;
  deposit: Deposit | null;
}

export type DepositStatus = "waiting" | "detected" | "confirming" | "confirmed" | "credited" | "expired" | "failed" | "amount_mismatch";

export type InvoiceStatus = "pending_payment" | "paid" | "expired" | "cancelled";

export interface Invoice {
  id: string;
  public_id: string;
  merchant_id: string;
  amount: string;
  description: string | null;
  external_reference: string | null;
  deposit_address: string;
  status: InvoiceStatus;
  expires_at: string;
  paid_at: string | null;
  cancelled_at: string | null;
  created_at: string;
  updated_at: string;
}

export type ApiKeyStatus = "active" | "revoked";

export interface ApiKey {
  id: string;
  merchant_id: string;
  label: string;
  key_prefix: string;
  status: ApiKeyStatus;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKey {
  raw_key: string;
}

export type WebhookStatus = "active" | "disabled";

export interface Webhook {
  id: string;
  merchant_id: string;
  url: string;
  event_types: string[];
  status: WebhookStatus;
  created_at: string;
  updated_at: string;
}

export interface WebhookCreated extends Webhook {
  secret: string;
}

export type WebhookDeliveryStatus = "pending" | "success" | "failed";

export interface WebhookDelivery {
  id: string;
  webhook_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  status: WebhookDeliveryStatus;
  attempts: number;
  max_attempts: number;
  next_attempt_at: string | null;
  last_response_status: number | null;
  last_response_snippet: string | null;
  last_error: string | null;
  created_at: string;
  delivered_at: string | null;
}

export interface TimelineDeposit {
  public_id: string;
  status: DepositStatus;
  expected_amount: string;
  received_amount: string | null;
  credited_amount: string | null;
  tx_hash: string | null;
  confirmations: number;
  required_confirmations: number;
  detected_at: string | null;
  confirmed_at: string | null;
  credited_at: string | null;
  failed_at: string | null;
}

export interface TimelineLedgerEntry {
  type: string;
  amount: string;
  currency: string;
  created_at: string;
}

export interface TimelineWebhookDelivery {
  webhook_id: string;
  event_type: string;
  status: WebhookDeliveryStatus;
  attempts: number;
  max_attempts: number;
  last_response_status: number | null;
  last_error: string | null;
  next_attempt_at: string | null;
  created_at: string;
  delivered_at: string | null;
}

export interface TimelineEvent {
  type: string;
  at: string;
  data: Record<string, unknown>;
}

export interface InvoiceTimeline {
  invoice: Invoice;
  deposit: TimelineDeposit | null;
  ledger_entry: TimelineLedgerEntry | null;
  webhook_deliveries: TimelineWebhookDelivery[];
  events: TimelineEvent[];
}

export interface PublicInvoice {
  public_id: string;
  amount: string;
  description: string | null;
  deposit_address: string;
  status: InvoiceStatus;
  expires_at: string;
  store_name: string | null;
}

export interface MerchantInvoiceStats {
  total: number;
  pending_payment: number;
  paid: number;
  expired: number;
  cancelled: number;
  paid_volume: string;
}

export interface MerchantWithdrawalStats {
  total: number;
  pending: number;
  approved: number;
  paid: number;
  rejected: number;
  cancelled: number;
  paid_volume: string;
}

export interface MerchantStatistics {
  invoices: MerchantInvoiceStats;
  withdrawals: MerchantWithdrawalStats;
}

export interface MerchantProfile {
  id: string;
  merchant_id: string;
  store_name: string | null;
  description: string | null;
  support_contact: string | null;
  created_at: string;
  updated_at: string;
}
export interface Deposit {
  id: string;
  public_id: string;
  account_id: string;
  network: string;
  asset: string;
  expected_amount: string;
  received_amount: string | null;
  credited_amount: string | null;
  deposit_address: string;
  tx_hash: string | null;
  confirmations: number;
  required_confirmations: number;
  status: DepositStatus;
  expires_at: string;
  detected_at: string | null;
  confirmed_at: string | null;
  credited_at: string | null;
  failed_at: string | null;
  created_at: string;
  updated_at: string;
}


export type RiskStatus = "healthy" | "warning" | "critical" | "stale" | "unknown";
export interface TreasurySummary {
  generated_at: string; external_observed_at: string | null; data_age_seconds: number | null;
  provider_status: string; external_bybit_usdt: string; external_bybit_usdc: string;
  total_external_stable_reserve: null; internal_user_liability_usdt: string;
  merchant_liability_usdt: string; total_internal_liability_usdt: string; frozen_usdt: string;
  pending_withdrawal_usdt: string; open_deal_exposure_usdt: string; owner_profit_usdt: string;
  required_reserve_usdt: string; available_reserve_usdt: string; reserve_surplus_usdt: string;
  reserve_deficit_usdt: string; coverage_ratio_bps: number | null; risk_status: RiskStatus;
  policy_version: number;
}
export interface RiskPolicyInput {
  reserve_coverage_enabled: boolean; minimum_reserve_ratio_bps: number;
  warning_reserve_ratio_bps: number; max_treasury_data_age_seconds: number;
  single_deal_enabled: boolean; max_single_deal_usdt: string | null;
  user_exposure_enabled: boolean; max_user_exposure_usdt: string | null;
  pending_withdrawals_enabled: boolean; max_pending_withdrawals_usdt: string | null;
  total_open_deals_enabled: boolean; max_total_open_deals_usdt: string | null;
  minimum_external_reserve_enabled: boolean; minimum_external_usdt_reserve: string | null;
}
export interface RiskPolicy extends RiskPolicyInput {
  id: string; version: number; status: "draft" | "active" | "retired";
  effective_from: string | null; created_at: string; activated_at: string | null;
}
export interface RiskPreview {
  snapshot: TreasurySummary;
  reserve_decision: "allow" | "warn" | "block";
  reason_code: string | null;
}

export type PayoutStatus = "requested" | "risk_review" | "approved" | "queued" | "execution_pending" | "executing" | "awaiting_manual_settlement" | "succeeded" | "failed" | "rejected" | "cancelled" | "reconciliation_required";
export interface PayoutApproval { id: string; approver_account_id: string; decision: "approved" | "rejected"; intent_hash: string; comment: string | null; created_at: string; }
export interface PayoutEvent { id: string; event: string; actor_account_id: string | null; event_metadata: Record<string, unknown>; created_at: string; }
export interface PayoutIntent {
  id: string; withdrawal_id: string; beneficiary_account_id: string; asset: string; amount: string;
  network: string; masked_destination: string; destination?: string | null; fee_amount: string; risk_policy_version: number;
  risk_decision: "allow" | "warn" | "block"; risk_reason: string | null; treasury_generated_at: string;
  approval_policy_version: number; required_approvals: number; approval_count: number;
  provider_name: string; provider_mode: "disabled" | "simulated" | "live"; status: PayoutStatus;
  external_reference_masked: string | null; failure_kind: string | null; failure_code: string | null;
  created_at: string; approved_at: string | null; queued_at: string | null;
  execution_started_at: string | null; executed_at: string | null; reconciled_at: string | null;
  approvals: PayoutApproval[]; events: PayoutEvent[];
}
export interface PayoutPolicyInput {
  payouts_enabled: boolean; auto_approval_enabled: boolean; default_required_approvals: number;
  dual_approval_threshold_usdt: string | null; high_value_required_approvals: number;
  max_single_payout_enabled: boolean; max_single_payout_usdt: string | null;
  max_daily_payout_enabled: boolean; max_daily_payout_usdt: string | null;
  max_hourly_payout_enabled: boolean; max_hourly_payout_usdt: string | null;
  max_pending_payout_enabled: boolean; max_pending_payout_usdt: string | null;
  max_asset_exposure_enabled: boolean; max_asset_exposure_usdt: string | null;
}
export interface PayoutPolicy extends PayoutPolicyInput { id: string; version: number; status: "draft" | "active" | "retired"; created_at: string; activated_at: string | null; }
export interface LivePayoutReadiness {
  ready: boolean;
  capabilities: string[];
  blocking_reasons: string[];
  checks: Record<string, boolean>;
}
export interface PayoutDestination {
  id: string; beneficiary_account_id: string; label: string; asset: string; network: string; masked_address: string;
  fingerprint: string; enabled: boolean; created_at: string; disabled_at: string | null;
}
export interface PayoutNetwork {
  id: string; asset: string; network: string; enabled: boolean;
  created_at: string; disabled_at: string | null;
}
