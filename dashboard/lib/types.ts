/* Real Conduit API response shapes (verified against the live regtest API).
   See design_handoff_conduit_console/README.md for the original mock shapes. */

export interface Agent {
  id: string; // "agt_..." — the canonical id used in all /v1/agents/{id} routes
  name: string; // human handle, e.g. "inference-router-04"
  pubkey: string | null;
  active: boolean;
  created_at: string; // ISO
  balance_sats: number; // denormalized spendable balance (now on the list response)
}

// ---- /v1/metrics (fleet dashboard) ----
export interface HourBucket {
  hour: string; // ISO UTC hour-start
  count: number;
  volume_sats: number;
}
export interface TopAgent {
  agent_id: string;
  name: string;
  tx_today: number;
  balance_sats: number;
  active: boolean;
}
export interface Metrics {
  treasury_sats: number;
  active_agents: number;
  total_agents: number;
  tx_per_min: number;
  avg_settlement_ms: number | null;
  p99_settlement_ms: number | null;
  hourly: HourBucket[];
  top_agents: TopAgent[];
  // Platform-fee revenue (the operator's per-transaction earnings, in sats).
  fee_revenue_total_sats: number;
  fee_revenue_today_sats: number;
  // Solvency (admin-only; zeroed/nulled for non-admin read keys server-side).
  liabilities_sats?: number;
  assets_sats?: number;
  solvency_ratio?: number | null;
  solvent?: boolean;
}

// ---- /v1/fees (platform-fee revenue; requires an admin-scope key) ----
export interface FeeDay {
  date: string; // "YYYY-MM-DD"
  sats: number;
  tx_count: number;
}
export interface Fees {
  total_collected_sats: number;
  total_collected_btc: number;
  today_sats: number;
  fees_by_day: FeeDay[]; // most-recent-first
}

// ---- /v1/treasury (owner/admin: revenue + on-chain withdrawal) ----
export interface WithdrawalItem {
  id: string;
  amount_sats: number;
  address: string;
  status: string; // pending | broadcast | failed
  txid: string | null;
  error: string | null;
  created_at: string;
}

export interface TreasuryOverview {
  // Revenue — accounting figure (Σ settled platform fees), commingled with node
  // liquidity, NOT a segregated wallet.
  revenue_total_sats: number;
  revenue_total_btc: number;
  revenue_today_sats: number;
  revenue_by_day: FeeDay[]; // most-recent-first
  // Node liquidity (assets backing agent balances).
  onchain_confirmed_sats: number;
  channel_local_sats: number;
  assets_sats: number;
  // Liabilities + resulting solvency.
  agent_liabilities_sats: number;
  solvent: boolean;
  solvency_ratio: number | null;
  // Max sats withdrawable on-chain now without breaching solvency.
  withdrawable_sats: number;
  fee_reserve_sats: number;
  recent_withdrawals: WithdrawalItem[];
  error: string | null;
}

export interface WithdrawResult {
  withdrawal_id: string;
  txid: string;
  amount_sats: number;
  address: string;
  status: string;
  assets_sats: number | null;
  agent_liabilities_sats: number | null;
  withdrawable_sats_remaining: number | null;
}

export interface Balance {
  agent_id: string;
  available_sats: number;
  pending_sats: number;
  total_sats: number;
}

export type TxDirection = "send" | "receive";
export type TxStatus = "settled" | "pending" | "failed";

export interface Transaction {
  id: string;
  agent_id: string;
  direction: TxDirection;
  amount_sats: number;
  fee_sats: number; // LND routing fee
  platform_fee_sats: number; // Conduit platform fee — the operator's revenue
  destination: string | null;
  payment_hash: string | null;
  status: TxStatus;
  memo: string | null;
  settled_at: string | null;
  latency_ms: number | null;
  created_at: string;
}

export interface Policy {
  id: string;
  agent_id: string;
  max_per_transaction: number | null;
  max_per_hour: number | null;
  max_per_day: number | null;
  max_per_minute_count: number;
  allowlist: string[];
  blocklist: string[];
  require_memo: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export type Scope = "admin" | "write" | "read" | "sandbox" | string;

export interface ApiKey {
  id: string; // "key_..."
  label: string;
  scope: Scope;
  prefix: string; // e.g. "ck_test_"
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

export interface ApiKeyCreated {
  id: string;
  label: string;
  scope: Scope;
  secret: string; // returned exactly once
  created_at: string;
}

export interface Invoice {
  id: string;
  agent_id: string;
  payment_request: string;
  payment_hash: string;
  amount_sats: number;
  memo: string | null;
}

export interface LedgerResult {
  agent_id: string;
  transaction_id: string;
  delta_sats: number;
  balance_sats: number;
}

export interface Health {
  ok: boolean;
  version: string;
  network: string; // regtest | testnet | mainnet
}

// ---- /v1/status (admin: node health + liquidity) ----
export interface NodeStatus {
  env: string;
  network: string;
  node: {
    alias: string;
    pubkey: string;
    block_height: number;
    synced_to_chain: boolean;
  };
  balance: {
    confirmed_sats: number;
    unconfirmed_sats: number;
    channel_local_sats: number;
    channel_remote_sats: number;
  };
  channels: { num_active: number };
}

export interface Webhook {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  secret?: string | null; // returned ONCE at creation (whsec_…), null on list
  created_at?: string;
}

// ---- /v1/decisions (inspectable payment Decision Record) ----
export type DecisionOutcome = "settled" | "failed" | "rejected";
export type DestinationKind = "bolt11" | "keysend" | "address";
export type AllowlistStatus = "allowed" | "no_allowlist" | "not_allowlisted" | "blocklisted";
export type ThresholdRule = "per_transaction" | "hourly" | "daily" | "rate" | "balance";
export type ThresholdUnit = "sats" | "count";

/** How one quantitative limit was evaluated for a payment — the margin data.
 *  margin_abs = limit − (current + attempted); negative ⇒ violated. Recorded even
 *  when the payment was ALLOWED, so a near-miss-that-passed is inspectable. */
export interface Threshold {
  rule: ThresholdRule;
  unit: ThresholdUnit;
  limit: number;
  attempted: number; // this payment's contribution to the window
  current: number; // prior usage already in the window
  margin_abs: number; // limit − (current + attempted); < 0 means violated
  margin_pct: number; // margin as a percent of the limit; < 0 means over
  violated: boolean;
}

/** A durable, inspectable payment decision — settled, failed, OR rejected — with
 *  the margin to each threshold, the applied-policy snapshot, and who initiated it.
 *  Never carries a secret/preimage. */
export interface Decision {
  id: string; // "dec_…"
  agent_id: string; // "agt_…"
  outcome: DecisionOutcome;
  reason_code: string | null;
  requested_sats: number;
  destination: string | null;
  destination_kind: DestinationKind | null;
  allowlist_status: AllowlistStatus | null;
  api_key_id: string | null; // id of the authorizing key — never the secret
  caller_tag: string | null; // opt-in caller/tool tag (X-Conduit-Caller)
  balance_at_decision_sats: number | null;
  thresholds: Threshold[];
  binding_rule: string | null; // the rule with the tightest margin
  min_margin_pct: number | null; // tightest margin across thresholds (% of its limit)
  policy_snapshot: Record<string, unknown> | null;
  policy_hash: string | null;
  tx_id: string | null; // linked transaction for allowed payments
  created_at: string; // ISO
}

/** Access tier the connected key has, derived from probing the API. */
export type AccessTier = "admin" | "member";
