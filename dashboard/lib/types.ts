/* Real Conduit API response shapes (verified against the live regtest API).
   See design_handoff_conduit_console/README.md for the original mock shapes. */

export interface Agent {
  id: string; // "agt_..." — the canonical id used in all /v1/agents/{id} routes
  name: string; // human handle, e.g. "inference-router-04"
  pubkey: string | null;
  active: boolean;
  created_at: string; // ISO
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
  fee_sats: number;
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
