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
