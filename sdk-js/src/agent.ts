import { Conduit, defaultClient } from "./client.js";
import { Policy } from "./policy.js";
import type {
  AgentJSON,
  Balance,
  CreateAgentOptions,
  InvoiceJSON,
  PayOptions,
  ReceiptJSON,
  TransactionJSON,
} from "./types.js";

/** Generate a fresh idempotency key. Prefers Web Crypto (Node 20+ and browsers). */
export function newIdempotencyKey(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c && typeof c.randomUUID === "function") return c.randomUUID();
  // Fallback for runtimes without Web Crypto (should not happen on Node >= 20).
  return `idem-${Date.now().toString(16)}-${Math.floor(Math.random() * 1e16).toString(16)}`;
}

export interface SendOptions {
  idempotencyKey?: string;
}

export interface Receipt {
  id: string;
  agentId: string;
  status: "pending" | "settled" | "failed";
  hash: string | null;
  amountSats: number;
  feeSats: number;
  platformFeeSats: number;
  settledInMs: number | null;
  destination: string | null;
  memo: string | null;
  createdAt: Date;
}

export interface Invoice {
  id: string;
  agentId: string;
  paymentRequest: string;
  paymentHash: string;
  amountSats: number;
  memo: string | null;
  status: "pending" | "settled" | "failed";
  expiresAt: Date;
  createdAt: Date;
}

export interface Transaction {
  id: string;
  agentId: string;
  direction: "send" | "receive";
  amountSats: number;
  feeSats: number;
  platformFeeSats: number;
  destination: string | null;
  paymentHash: string | null;
  status: "pending" | "settled" | "failed";
  memo: string | null;
  settledAt: Date | null;
  latencyMs: number | null;
  createdAt: Date;
}

export interface LedgerAdjustment {
  agentId: string;
  transactionId: string;
  /** positive = credit, negative = debit */
  deltaSats: number;
  balanceSats: number;
}

export interface LedgerAdjustJSON {
  agent_id: string;
  transaction_id: string;
  delta_sats: number;
  balance_sats: number;
}

export function fromLedger(d: LedgerAdjustJSON): LedgerAdjustment {
  return {
    agentId: d.agent_id,
    transactionId: d.transaction_id,
    deltaSats: d.delta_sats,
    balanceSats: d.balance_sats,
  };
}

export function fromReceipt(r: ReceiptJSON): Receipt {
  return {
    id: r.id,
    agentId: r.agent_id,
    status: r.status,
    hash: r.hash,
    amountSats: r.amount_sats,
    feeSats: r.fee_sats,
    platformFeeSats: r.platform_fee_sats ?? 0,
    settledInMs: r.settled_in_ms,
    destination: r.destination,
    memo: r.memo,
    createdAt: new Date(r.created_at),
  };
}
export function fromInvoice(i: InvoiceJSON): Invoice {
  return {
    id: i.id,
    agentId: i.agent_id,
    paymentRequest: i.payment_request,
    paymentHash: i.payment_hash,
    amountSats: i.amount_sats,
    memo: i.memo,
    status: i.status,
    expiresAt: new Date(i.expires_at),
    createdAt: new Date(i.created_at),
  };
}
export function fromTx(t: TransactionJSON): Transaction {
  return {
    id: t.id,
    agentId: t.agent_id,
    direction: t.direction,
    amountSats: t.amount_sats,
    feeSats: t.fee_sats,
    platformFeeSats: t.platform_fee_sats ?? 0,
    destination: t.destination,
    paymentHash: t.payment_hash,
    status: t.status,
    memo: t.memo,
    settledAt: t.settled_at ? new Date(t.settled_at) : null,
    latencyMs: t.latency_ms,
    createdAt: new Date(t.created_at),
  };
}

export class Agent {
  readonly id: string;
  readonly name: string;
  readonly pubkey: string | null;
  active: boolean;
  readonly createdAt: Date;
  readonly policy: Policy;
  private readonly client: Conduit;

  private constructor(data: AgentJSON, client: Conduit) {
    this.id = data.id;
    this.name = data.name;
    this.pubkey = data.pubkey;
    this.active = data.active;
    this.createdAt = new Date(data.created_at);
    this.client = client;
    this.policy = new Policy(this, client);
  }

  static async create(opts: CreateAgentOptions, client?: Conduit): Promise<Agent> {
    const c = client ?? defaultClient();
    const data = await c.post<AgentJSON>("/v1/agents", {
      name: opts.name,
      daily_limit: opts.dailyLimit,
      metadata: opts.metadata,
    });
    return new Agent(data, c);
  }

  static async get(id: string, client?: Conduit): Promise<Agent> {
    const c = client ?? defaultClient();
    const data = await c.get<AgentJSON>(`/v1/agents/${id}`);
    return new Agent(data, c);
  }

  static async list(client?: Conduit): Promise<Agent[]> {
    const c = client ?? defaultClient();
    const data = await c.get<{ data: AgentJSON[] }>("/v1/agents");
    return data.data.map((d) => new Agent(d, c));
  }

  async pay(opts: PayOptions): Promise<Receipt> {
    const data = await this.client.post<ReceiptJSON>(
      "/v1/payments/pay",
      {
        agent_id: this.id,
        to: opts.to,
        sats: opts.sats,
        memo: opts.memo,
        metadata: opts.metadata,
      },
      { idempotencyKey: opts.idempotencyKey ?? newIdempotencyKey() },
    );
    return fromReceipt(data);
  }

  async sendInvoice(
    paymentRequest: string,
    opts: { sats?: number; memo?: string; idempotencyKey?: string } = {},
  ): Promise<Receipt> {
    const data = await this.client.post<ReceiptJSON>(
      "/v1/payments/send",
      {
        agent_id: this.id,
        payment_request: paymentRequest,
        sats: opts.sats,
        memo: opts.memo,
      },
      { idempotencyKey: opts.idempotencyKey ?? newIdempotencyKey() },
    );
    return fromReceipt(data);
  }

  async keysend(
    destPubkey: string,
    sats: number,
    memo?: string,
    opts: SendOptions = {},
  ): Promise<Receipt> {
    const data = await this.client.post<ReceiptJSON>(
      "/v1/payments/send",
      {
        agent_id: this.id,
        dest_pubkey: destPubkey,
        sats,
        memo,
      },
      { idempotencyKey: opts.idempotencyKey ?? newIdempotencyKey() },
    );
    return fromReceipt(data);
  }

  async receive(amount: number, opts: { memo?: string; expiry?: number } = {}): Promise<Invoice> {
    const data = await this.client.post<InvoiceJSON>("/v1/invoices", {
      agent_id: this.id,
      amount,
      memo: opts.memo,
      expiry: opts.expiry ?? 3600,
    });
    return fromInvoice(data);
  }

  /** Operator top-up: credit this agent's virtual balance (admin scope). */
  async credit(
    sats: number,
    opts: { reason?: string; metadata?: Record<string, unknown> } = {},
  ): Promise<LedgerAdjustment> {
    const body: Record<string, unknown> = { sats };
    if (opts.reason !== undefined) body.reason = opts.reason;
    if (opts.metadata !== undefined) body.metadata = opts.metadata;
    return fromLedger(
      await this.client.post<LedgerAdjustJSON>(`/v1/agents/${this.id}/credit`, body),
    );
  }

  /** Operator sweep: debit this agent's virtual balance (admin scope). */
  async debit(
    sats: number,
    opts: { reason?: string; metadata?: Record<string, unknown> } = {},
  ): Promise<LedgerAdjustment> {
    const body: Record<string, unknown> = { sats };
    if (opts.reason !== undefined) body.reason = opts.reason;
    if (opts.metadata !== undefined) body.metadata = opts.metadata;
    return fromLedger(
      await this.client.post<LedgerAdjustJSON>(`/v1/agents/${this.id}/debit`, body),
    );
  }

  async balance(): Promise<Balance> {
    const data = await this.client.get<{
      available_sats: number;
      pending_sats: number;
      total_sats: number;
    }>(`/v1/agents/${this.id}/balance`);
    return {
      available: data.available_sats,
      pending: data.pending_sats,
      total: data.total_sats,
    };
  }

  async transactions(limit = 50, direction?: "send" | "receive"): Promise<Transaction[]> {
    const data = await this.client.get<{ data: TransactionJSON[] }>(
      `/v1/agents/${this.id}/transactions`,
      direction ? { limit, direction } : { limit },
    );
    return data.data.map(fromTx);
  }

  async deactivate(): Promise<void> {
    await this.client.delete(`/v1/agents/${this.id}`);
    this.active = false;
  }
}
