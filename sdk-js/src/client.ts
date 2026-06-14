import { AuthenticationError, ConduitError, throwForResponse } from "./errors.js";

const DEFAULT_BASE_URL = "https://api.conduit.energy";
const DEFAULT_MAX_RETRIES = 3;
const DEFAULT_BACKOFF_BASE_MS = 1000; // 1s, 2s, 4s
// Cap how long we'll honor a server-provided Retry-After.
const MAX_RETRY_AFTER_MS = 60_000;

function isRetryableStatus(status: number): boolean {
  return status === 429 || (status >= 500 && status < 600);
}

/**
 * Compute the backoff delay (ms) for a given attempt. A usable, non-negative
 * `Retry-After` (seconds) overrides the exponential schedule and is capped.
 * Empty / whitespace / non-numeric / negative values fall back to exponential
 * backoff — matching the Python SDK exactly. `Retry-After: 0` means retry now.
 */
export function backoffDelayMs(
  attempt: number,
  retryAfter: string | null,
  baseMs: number,
  capMs: number,
): number {
  let delayMs = baseMs * 2 ** attempt;
  if (retryAfter != null && retryAfter.trim() !== "") {
    const secs = Number(retryAfter);
    if (Number.isFinite(secs) && secs >= 0) {
      delayMs = Math.min(secs * 1000, capMs);
    }
  }
  return delayMs;
}

export interface ConduitOptions {
  apiKey?: string;
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  /** Max automatic retries on 429 / 5xx / network errors. Default 3. */
  maxRetries?: number;
  /** Base for exponential backoff in ms (base * 2**attempt). Default 1000. */
  retryBackoffBaseMs?: number;
}

export interface RequestOptions {
  /**
   * Idempotency key sent as the `Idempotency-Key` header and reused across
   * every retry of this request — so a retried payment can never settle twice.
   */
  idempotencyKey?: string;
}

export class Conduit {
  readonly apiKey: string;
  readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly backoffBaseMs: number;

  constructor(opts: ConduitOptions = {}) {
    const key = opts.apiKey ?? (globalThis as any).process?.env?.CONDUIT_API_KEY;
    if (!key) {
      throw new AuthenticationError(
        "No API key. Set CONDUIT_API_KEY env var or pass { apiKey } to Conduit().",
      );
    }
    this.apiKey = key;
    this.baseUrl = (
      opts.baseUrl ??
      (globalThis as any).process?.env?.CONDUIT_API_URL ??
      DEFAULT_BASE_URL
    ).replace(/\/$/, "");
    this.fetchImpl = opts.fetchImpl ?? fetch;
    this.timeoutMs = opts.timeoutMs ?? 30_000;
    this.maxRetries = Math.max(0, opts.maxRetries ?? DEFAULT_MAX_RETRIES);
    this.backoffBaseMs = Math.max(0, opts.retryBackoffBaseMs ?? DEFAULT_BACKOFF_BASE_MS);
  }

  async get<T>(path: string, query?: Record<string, string | number>): Promise<T> {
    let url = this.baseUrl + path;
    if (query) {
      const qs = new URLSearchParams(
        Object.entries(query).map(([k, v]) => [k, String(v)]),
      );
      url += `?${qs.toString()}`;
    }
    return this.request<T>("GET", url);
  }
  async post<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
    return this.request<T>("POST", this.baseUrl + path, body, opts?.idempotencyKey);
  }
  async put<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("PUT", this.baseUrl + path, body);
  }
  async delete<T>(path: string): Promise<T> {
    return this.request<T>("DELETE", this.baseUrl + path);
  }

  private async request<T>(
    method: string,
    url: string,
    body?: unknown,
    idempotencyKey?: string,
  ): Promise<T> {
    let attempt = 0;
    // Build headers ONCE so the idempotency key is identical across retries.
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.apiKey}`,
      "Content-Type": "application/json",
      "User-Agent": "conduit-js/0.8.4",
    };
    if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;

    // A non-idempotent write (a POST WITHOUT an Idempotency-Key — e.g. credit /
    // debit / createInvoice / policy.attach) must NOT be auto-replayed on an
    // ambiguous failure (network drop / 5xx): the server may have already applied
    // it, so a retry would double-apply (audit M8). GET/DELETE are idempotent; a
    // keyed POST dedupes server-side; a 429 (rate-limited) was never processed.
    const replaySafe = method === "GET" || method === "DELETE" || idempotencyKey != null;

    while (true) {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), this.timeoutMs);
      let res: Response;
      try {
        res = await this.fetchImpl(url, {
          method,
          signal: ctl.signal,
          headers,
          body: body === undefined ? undefined : JSON.stringify(body),
        });
      } catch (e) {
        clearTimeout(timer);
        // Network/timeout = ambiguous (may have been applied) — only auto-retry
        // when the request is replay-safe.
        if (replaySafe && attempt < this.maxRetries) {
          await this.backoff(attempt, null);
          attempt++;
          continue;
        }
        throw new ConduitError(`Network error: ${(e as Error).message}`);
      }
      clearTimeout(timer);

      if (res.status >= 400) {
        // 429 is always retryable (rate-limited → never processed); 5xx is
        // ambiguous, so only replay it when the request is replay-safe.
        const statusRetryable =
          res.status === 429 || (isRetryableStatus(res.status) && replaySafe);
        if (statusRetryable && attempt < this.maxRetries) {
          await this.backoff(attempt, res.headers.get("Retry-After"));
          attempt++;
          continue;
        }
        let parsed: unknown;
        try {
          parsed = await res.json();
        } catch {
          parsed = { detail: { detail: `HTTP ${res.status}` } };
        }
        throwForResponse(res.status, parsed);
      }
      if (res.status === 204) return undefined as T;
      return (await res.json()) as T;
    }
  }

  private async backoff(attempt: number, retryAfter: string | null): Promise<void> {
    const delayMs = backoffDelayMs(
      attempt,
      retryAfter,
      this.backoffBaseMs,
      MAX_RETRY_AFTER_MS,
    );
    if (delayMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
  }
}

let _default: Conduit | undefined;
export function defaultClient(): Conduit {
  if (!_default) _default = new Conduit();
  return _default;
}
export function setDefaultClient(c: Conduit): void {
  _default = c;
}
