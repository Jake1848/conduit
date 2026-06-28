export type Scope = "read" | "write" | "admin";
export type TxStatus = "pending" | "settled" | "failed";
export type Direction = "send" | "receive";

export interface AgentJSON {
  id: string;
  name: string;
  pubkey: string | null;
  active: boolean;
  created_at: string;
}

export interface ReceiptJSON {
  id: string;
  agent_id: string;
  status: TxStatus;
  hash: string | null;
  amount_sats: number;
  fee_sats: number;
  platform_fee_sats: number;
  settled_in_ms: number | null;
  destination: string | null;
  memo: string | null;
  created_at: string;
}

export interface InvoiceJSON {
  id: string;
  agent_id: string;
  payment_request: string;
  payment_hash: string;
  amount_sats: number;
  memo: string | null;
  status: TxStatus;
  expires_at: string;
  created_at: string;
}

export interface TransactionJSON {
  id: string;
  agent_id: string;
  direction: Direction;
  amount_sats: number;
  fee_sats: number;
  platform_fee_sats: number;
  destination: string | null;
  payment_hash: string | null;
  status: TxStatus;
  memo: string | null;
  settled_at: string | null;
  latency_ms: number | null;
  created_at: string;
}

// ---------- Decisions (inspectable payment decision record) ----------

export type DecisionOutcome = "settled" | "failed" | "rejected";
export type DestinationKind = "bolt11" | "keysend" | "address";
export type AllowlistStatus = "allowed" | "no_allowlist" | "not_allowlisted" | "blocklisted";
export type ThresholdRule = "per_transaction" | "hourly" | "daily" | "rate" | "balance";
export type ThresholdUnit = "sats" | "count";

export interface ThresholdJSON {
  rule: ThresholdRule;
  unit: ThresholdUnit;
  limit: number;
  attempted: number;
  current: number;
  margin_abs: number;
  margin_pct: number;
  violated: boolean;
}

export interface DecisionJSON {
  id: string;
  agent_id: string;
  outcome: DecisionOutcome;
  reason_code: string | null;
  requested_sats: number;
  destination: string | null;
  destination_kind: DestinationKind | null;
  allowlist_status: AllowlistStatus | null;
  api_key_id: string | null;
  caller_tag: string | null;
  balance_at_decision_sats: number | null;
  thresholds: ThresholdJSON[];
  binding_rule: string | null;
  min_margin_pct: number | null;
  policy_snapshot: Record<string, unknown> | null;
  policy_hash: string | null;
  tx_id: string | null;
  created_at: string;
}

/** How one quantitative limit was evaluated for a payment — the margin data. */
export interface Threshold {
  rule: ThresholdRule;
  unit: ThresholdUnit;
  limit: number;
  /** this payment's contribution to the window */
  attempted: number;
  /** prior usage already in the window */
  current: number;
  /** limit - (current + attempted); < 0 means violated — present even when ALLOWED */
  marginAbs: number;
  /** margin as a percent of the limit; < 0 means over */
  marginPct: number;
  violated: boolean;
}

/**
 * A durable, inspectable payment decision — settled, failed, OR rejected — with
 * the margin to each threshold, the applied-policy snapshot, and who initiated it.
 * No secret/preimage is ever included.
 */
export interface Decision {
  id: string;
  agentId: string;
  outcome: DecisionOutcome;
  reasonCode: string | null;
  requestedSats: number;
  destination: string | null;
  destinationKind: DestinationKind | null;
  allowlistStatus: AllowlistStatus | null;
  /** id of the authorizing key — never the secret */
  apiKeyId: string | null;
  /** opt-in caller/tool tag (X-Conduit-Caller) */
  callerTag: string | null;
  balanceAtDecisionSats: number | null;
  /** per-limit margin breakdown — present even when ALLOWED (a near-miss that passed) */
  thresholds: Threshold[];
  /** the rule with the tightest margin */
  bindingRule: string | null;
  /** tightest margin across thresholds (% of its limit) */
  minMarginPct: number | null;
  /** the applied policy at decision time (reconstructable post-edit) */
  policySnapshot: Record<string, unknown> | null;
  policyHash: string | null;
  /** linked transaction for allowed payments */
  txId: string | null;
  createdAt: Date;
}

export interface PolicyAttachOptions {
  maxPerTransaction?: number;
  maxPerHour?: number;
  maxPerDay?: number;
  maxPerMinuteCount?: number;
  allowlist?: string[];
  blocklist?: string[];
  requireMemo?: boolean;
  enabled?: boolean;
}

export interface PayOptions {
  to: string;
  sats: number;
  memo?: string;
  metadata?: Record<string, unknown>;
  /** Reuse this key to make a manual retry idempotent. Auto-generated if omitted. */
  idempotencyKey?: string;
}

export interface CreateAgentOptions {
  name: string;
  dailyLimit?: number;
  metadata?: Record<string, unknown>;
}

export interface Balance {
  available: number;
  pending: number;
  total: number;
}
