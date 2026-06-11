/* Direct client for the Conduit API. The browser talks to the API directly using
   the operator's API key (stored in localStorage); the API enables this via CORS
   (ALLOWED_ORIGINS must include this app's origin). No BFF / server layer. */

import type {
  Agent,
  ApiKey,
  ApiKeyCreated,
  Balance,
  Fees,
  Health,
  Invoice,
  LedgerResult,
  Metrics,
  Policy,
  Scope,
  Transaction,
  TreasuryOverview,
  Webhook,
  WithdrawResult,
} from "./types";

function normalizeUrl(url: string): string {
  return url.trim().replace(/\/+$/, "");
}

/** Compile-time default base URL (from env at build, falls back to the hosted demo).
 *  At runtime the operator-configured apiUrl in localStorage takes precedence so the
 *  same dashboard build can drive ANY self-hosted Conduit instance. */
export const DEFAULT_API_BASE = normalizeUrl(
  process.env.NEXT_PUBLIC_API_URL || "https://api.conduit.energy",
);

const KEY_STORAGE = "conduit_api_key";
const URL_STORAGE = "conduit_api_url";

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

/** Operator-configured API base URL (persisted in localStorage). Falls back to the
 *  build-time default. This is the base for ALL API calls. */
export function getStoredApiUrl(): string {
  if (typeof window === "undefined") return DEFAULT_API_BASE;
  const stored = window.localStorage.getItem(URL_STORAGE);
  return stored ? normalizeUrl(stored) : DEFAULT_API_BASE;
}
export function setStoredApiUrl(url: string): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(URL_STORAGE, normalizeUrl(url));
  }
}
export function clearStoredApiUrl(): void {
  if (typeof window !== "undefined") window.localStorage.removeItem(URL_STORAGE);
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
  baseUrl?: string; // override the stored API URL (used during login probing)
  idempotencyKey?: string;
  signal?: AbortSignal;
}

async function request<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const key = opts.key ?? getStoredKey();
  const base = opts.baseUrl ? normalizeUrl(opts.baseUrl) : getStoredApiUrl();
  const headers: Record<string, string> = {};
  if (key) headers["Authorization"] = `Bearer ${key}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey;

  let res: Response;
  try {
    res = await fetch(`${base}${path}`, {
      method: opts.method || "GET",
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (e) {
    // Preserve cancellation so callers can distinguish an aborted request
    // (e.g. a component unmount mid-pagination) from a real network failure.
    if ((e as Error)?.name === "AbortError") throw e;
    throw new ApiError(0, "NETWORK", `Cannot reach the Conduit API at ${base}. ${(e as Error).message}`);
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
  // The API paginates /v1/agents (default 50, max 500). Page through with
  // has_more so the console always sees the WHOLE fleet (treasury totals,
  // active counts, audit name resolution all depend on the full list).
  listAgents: async (signal?: AbortSignal): Promise<Agent[]> => {
    const all: Agent[] = [];
    const limit = 500;
    let offset = 0;
    // Safety cap (100k agents) so a misbehaving has_more can't loop forever.
    for (let page = 0; page < 200; page++) {
      const r = await request<{ data: Agent[]; has_more?: boolean }>(
        `/v1/agents?limit=${limit}&offset=${offset}`,
        { signal },
      );
      all.push(...r.data);
      if (!r.has_more || r.data.length === 0) break;
      offset += limit;
    }
    return all;
  },
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

  // ---- fleet metrics + global feed (server-aggregated; no per-agent fan-out) ----
  getMetrics: (signal?: AbortSignal) => request<Metrics>("/v1/metrics", { signal }),

  // ---- platform-fee revenue (admin-scope key required) ----
  getFees: (signal?: AbortSignal) => request<Fees>("/v1/fees", { signal }),

  // ---- treasury: revenue + node liquidity + solvency + on-chain withdrawal (admin) ----
  getTreasury: (signal?: AbortSignal) =>
    request<TreasuryOverview>("/v1/treasury/overview", { signal }),
  // idempotencyKey MUST be stable across retries of the SAME withdrawal intent
  // (a lost-response retry with a fresh key would double-broadcast). The caller
  // owns the key and only rotates it for a genuinely new withdrawal.
  withdraw: (amountSats: number, address: string, satPerVbyte: number | undefined, idempotencyKey: string) =>
    request<WithdrawResult>("/v1/treasury/withdraw", {
      method: "POST",
      body: {
        amount_sats: amountSats,
        address,
        ...(satPerVbyte ? { sat_per_vbyte: satPerVbyte } : {}),
      },
      idempotencyKey,
    }),
  getRecentTransactions: (limit = 50, signal?: AbortSignal) =>
    request<{ data: Transaction[]; has_more: boolean }>(
      `/v1/transactions/recent?limit=${limit}`,
      { signal },
    ),

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
