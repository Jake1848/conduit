import { Conduit } from "./client.js";
import type { ConduitOptions } from "./client.js";
import {
  Agent,
  fromInvoice,
  fromLedger,
  fromReceipt,
  fromTx,
  newIdempotencyKey,
} from "./agent.js";
import type {
  Invoice,
  LedgerAdjustJSON,
  LedgerAdjustment,
  Receipt,
  Transaction,
} from "./agent.js";
import type {
  Balance,
  CreateAgentOptions,
  InvoiceJSON,
  ReceiptJSON,
  TransactionJSON,
} from "./types.js";

export interface SendPaymentOptions {
  /** keysend destination node pubkey */
  destPubkey?: string;
  /** BOLT11 invoice string */
  paymentRequest?: string;
  sats?: number;
  memo?: string;
  idempotencyKey?: string;
}

export interface FundOptions {
  reason?: string;
  metadata?: Record<string, unknown>;
}

/**
 * A high-level, client-centric handle on a Conduit instance.
 *
 * The `Agent` active-record API is idiomatic, but many developers expect a
 * single client with `createAgent` / `creditAgent` / `sendPayment` methods.
 * `ConduitClient` provides exactly that over the same retrying, idempotent HTTP
 * client.
 *
 *     const client = new ConduitClient({ baseUrl: "...", apiKey: "ck_test_..." });
 *     const agent = await client.createAgent({ name: "sdk-test" });
 *     await client.creditAgent(agent.id, { sats: 10_000 });
 *     const receipt = await client.sendPayment(agent.id, { destPubkey: "02ab...", sats: 500 });
 */
export class ConduitClient {
  readonly http: Conduit;

  constructor(opts: ConduitOptions = {}) {
    this.http = new Conduit(opts);
  }

  // ---- agents ----

  createAgent(opts: CreateAgentOptions): Promise<Agent> {
    return Agent.create(opts, this.http);
  }

  getAgent(agentId: string): Promise<Agent> {
    return Agent.get(agentId, this.http);
  }

  listAgents(): Promise<Agent[]> {
    return Agent.list(this.http);
  }

  async deactivateAgent(agentId: string): Promise<void> {
    await this.http.delete(`/v1/agents/${agentId}`);
  }

  // ---- funding (operator / admin scope) ----

  async creditAgent(
    agentId: string,
    opts: { sats: number } & FundOptions,
  ): Promise<LedgerAdjustment> {
    const body: Record<string, unknown> = { sats: opts.sats };
    if (opts.reason !== undefined) body.reason = opts.reason;
    if (opts.metadata !== undefined) body.metadata = opts.metadata;
    return fromLedger(
      await this.http.post<LedgerAdjustJSON>(`/v1/agents/${agentId}/credit`, body),
    );
  }

  async debitAgent(
    agentId: string,
    opts: { sats: number } & FundOptions,
  ): Promise<LedgerAdjustment> {
    const body: Record<string, unknown> = { sats: opts.sats };
    if (opts.reason !== undefined) body.reason = opts.reason;
    if (opts.metadata !== undefined) body.metadata = opts.metadata;
    return fromLedger(
      await this.http.post<LedgerAdjustJSON>(`/v1/agents/${agentId}/debit`, body),
    );
  }

  // ---- balance / ledger ----

  async getBalance(agentId: string): Promise<Balance> {
    const d = await this.http.get<{
      available_sats: number;
      pending_sats: number;
      total_sats: number;
    }>(`/v1/agents/${agentId}/balance`);
    return { available: d.available_sats, pending: d.pending_sats, total: d.total_sats };
  }

  async listTransactions(
    agentId: string,
    opts: { limit?: number; direction?: "send" | "receive" } = {},
  ): Promise<Transaction[]> {
    const query: Record<string, string | number> = { limit: opts.limit ?? 50 };
    if (opts.direction) query.direction = opts.direction;
    const d = await this.http.get<{ data: TransactionJSON[] }>(
      `/v1/agents/${agentId}/transactions`,
      query,
    );
    return d.data.map(fromTx);
  }

  // ---- payments ----

  async sendPayment(agentId: string, opts: SendPaymentOptions): Promise<Receipt> {
    if (!opts.destPubkey && !opts.paymentRequest) {
      throw new Error("sendPayment requires destPubkey or paymentRequest");
    }
    const body: Record<string, unknown> = { agent_id: agentId, memo: opts.memo };
    if (opts.destPubkey !== undefined) body.dest_pubkey = opts.destPubkey;
    if (opts.paymentRequest !== undefined) body.payment_request = opts.paymentRequest;
    if (opts.sats !== undefined) body.sats = opts.sats;
    return fromReceipt(
      await this.http.post<ReceiptJSON>("/v1/payments/send", body, {
        idempotencyKey: opts.idempotencyKey ?? newIdempotencyKey(),
      }),
    );
  }

  async pay(
    agentId: string,
    opts: { to: string; sats: number; memo?: string; idempotencyKey?: string },
  ): Promise<Receipt> {
    return fromReceipt(
      await this.http.post<ReceiptJSON>(
        "/v1/payments/pay",
        { agent_id: agentId, to: opts.to, sats: opts.sats, memo: opts.memo },
        { idempotencyKey: opts.idempotencyKey ?? newIdempotencyKey() },
      ),
    );
  }

  async createInvoice(
    agentId: string,
    opts: { amount: number; memo?: string; expiry?: number },
  ): Promise<Invoice> {
    return fromInvoice(
      await this.http.post<InvoiceJSON>("/v1/invoices", {
        agent_id: agentId,
        amount: opts.amount,
        memo: opts.memo,
        expiry: opts.expiry ?? 3600,
      }),
    );
  }

  // ---- operator revenue / metrics ----

  getFees(): Promise<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>("/v1/fees");
  }

  getMetrics(): Promise<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>("/v1/metrics");
  }
}
