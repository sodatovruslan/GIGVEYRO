export type UserRole = "owner" | "user" | "merchant";

export interface Account {
  id: string;
  username: string;
  role: UserRole;
  full_name: string;
  email: string | null;
  phone: string | null;
  is_active: boolean;
  is_verified: boolean;
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

export interface MerchantWallet {
  currency: "USDT" | "usdt";
  available_balance: string;
  held_balance: string;
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
