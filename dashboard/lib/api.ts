/* Direct client for the Conduit API. The browser talks to the API directly using
   the operator's API key (stored in localStorage); the API enables this via CORS
   (ALLOWED_ORIGINS must include this app's origin). No BFF / server layer. */

import type {
  Agent,
  ApiKey,
  ApiKeyCreated,
  Balance,
  Health,
  Invoice,
  LedgerResult,
  Policy,
  Scope,
  Transaction,
  Webhook,
} from "./types";

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8002"
).replace(/\/$/, "");

const KEY_STORAGE = "conduit_api_key";

export function getStoredKey(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(KEY_STORAGE);
}
export function setStoredKey(key: string): void {
  if (typeof window !== "undefined") window.localStorage.setItem(KEY_STORAGE, key);
}
export function clearStoredKey(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(KEY_STORAGE);
}

export class ApiError extends Error {
  status: number;
  code: string | null;
  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

interface RequestOpts {
  method?: string;
  body?: unknown;
  key?: string; // override the stored key (used during login probing)
  idempotencyKey?: string;
  signal?: AbortSignal;
}

async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const key = opts.key ?? getStoredKey();
  const headers: Record<string, string> = {};
  if (key) headers["Authorization"] = `Bearer ${key}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: opts.method || "GET",
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (e) {
    throw new ApiError(0, "NETWORK", `Cannot reach the Conduit API at ${API_BASE}. ${(e as Error).message}`);
  }

  if (res.status === 204) return undefined as T;

  let data: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    const detail = (data as { detail?: { code?: string; detail?: string } | string })?.detail;
    let code: string | null = null;
    let msg = `Request failed (${res.status})`;
    if (detail && typeof detail === "object") {
      code = detail.code ?? null;
      msg = detail.detail || detail.code || msg;
    } else if (typeof detail === "string") {
      msg = detail;
    }
    throw new ApiError(res.status, code, msg);
  }
  return data as T;
}

function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "id-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export const api = {
  uuid,

  // ---- public ----
  health: () => request<Health>("/v1/health"),

  // ---- agents ----
  listAgents: (signal?: AbortSignal) =>
    request<{ data: Agent[] }>("/v1/agents", { signal }).then((r) => r.data),
  getAgent: (id: string, signal?: AbortSignal) => request<Agent>(`/v1/agents/${id}`, { signal }),
  getBalance: (id: string, signal?: AbortSignal) =>
    request<Balance>(`/v1/agents/${id}/balance`, { signal }),
  getTransactions: (id: string, limit = 50, signal?: AbortSignal) =>
    request<{ data: Transaction[]; has_more: boolean }>(
      `/v1/agents/${id}/transactions?limit=${limit}`,
      { signal },
    ),
  createAgent: (name: string, dailyLimit?: number) =>
    request<Agent>("/v1/agents", {
      method: "POST",
      body: { name, ...(dailyLimit ? { daily_limit: dailyLimit } : {}) },
      idempotencyKey: uuid(),
    }),

  // ---- ledger ----
  credit: (id: string, sats: number, reason = "console credit") =>
    request<LedgerResult>(`/v1/agents/${id}/credit`, {
      method: "POST",
      body: { sats, reason },
      idempotencyKey: uuid(),
    }),
  debit: (id: string, sats: number, reason = "console debit") =>
    request<LedgerResult>(`/v1/agents/${id}/debit`, {
      method: "POST",
      body: { sats, reason },
      idempotencyKey: uuid(),
    }),

  // ---- policy ----
  getPolicy: (id: string, signal?: AbortSignal) =>
    request<Policy>(`/v1/agents/${id}/policy`, { signal }),
  savePolicy: (
    id: string,
    body: {
      max_per_transaction?: number | null;
      max_per_hour?: number | null;
      max_per_day?: number | null;
      allowlist?: string[];
      blocklist?: string[];
    },
  ) => request<Policy>(`/v1/agents/${id}/policy`, { method: "POST", body }),

  // ---- invoices ----
  createInvoice: (agentId: string, amount: number, memo?: string) =>
    request<Invoice>("/v1/invoices", {
      method: "POST",
      body: { agent_id: agentId, amount, ...(memo ? { memo } : {}) },
    }),

  // ---- api keys ----
  listKeys: (key?: string, signal?: AbortSignal) =>
    request<{ data: ApiKey[] }>("/v1/api-keys", { key, signal }).then((r) => r.data),
  createKey: (scope: Scope, label: string) =>
    request<ApiKeyCreated>("/v1/api-keys", { method: "POST", body: { scope, label } }),
  revokeKey: (id: string) => request<void>(`/v1/api-keys/${id}`, { method: "DELETE" }),

  // ---- webhooks ----
  listWebhooks: () => request<{ data: Webhook[] }>("/v1/webhooks").then((r) => r.data),
  createWebhook: (url: string, events: string[]) =>
    request<Webhook>("/v1/webhooks", { method: "POST", body: { url, events } }),
  deleteWebhook: (id: string) => request<void>(`/v1/webhooks/${id}`, { method: "DELETE" }),

  request,
};
