import { AuthenticationError, ConduitError, throwForResponse } from "./errors.js";

const DEFAULT_BASE_URL = "https://api.conduit.energy";

export interface ConduitOptions {
  apiKey?: string;
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

export class Conduit {
  readonly apiKey: string;
  readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

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
  async post<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("POST", this.baseUrl + path, body);
  }
  async put<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("PUT", this.baseUrl + path, body);
  }
  async delete<T>(path: string): Promise<T> {
    return this.request<T>("DELETE", this.baseUrl + path);
  }

  private async request<T>(method: string, url: string, body?: unknown): Promise<T> {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), this.timeoutMs);
    let res: Response;
    try {
      res = await this.fetchImpl(url, {
        method,
        signal: ctl.signal,
        headers: {
          Authorization: `Bearer ${this.apiKey}`,
          "Content-Type": "application/json",
          "User-Agent": "conduit-js/0.1.0",
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      clearTimeout(timer);
      throw new ConduitError(`Network error: ${(e as Error).message}`);
    }
    clearTimeout(timer);

    if (res.status >= 400) {
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

let _default: Conduit | undefined;
export function defaultClient(): Conduit {
  if (!_default) _default = new Conduit();
  return _default;
}
export function setDefaultClient(c: Conduit): void {
  _default = c;
}
