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

export interface Webhook {
  id: string;
  url: string;
  events: string[];
  active: boolean;
}

/** Access tier the connected key has, derived from probing the API. */
export type AccessTier = "admin" | "member";
