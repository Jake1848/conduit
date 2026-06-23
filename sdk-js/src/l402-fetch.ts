/**
 * fetchWithL402 — a global-fetch wrapper that transparently handles L402 tolls.
 *
 * On a 402 response the wrapper:
 *   1. Parses the WWW-Authenticate header.
 *   2. Pays (or returns a cached token) via the injected L402Engine.
 *   3. Replays the original request with the Authorization header.
 *
 * Non-402 responses pass through unchanged. The wrapper is a drop-in replacement
 * for the global `fetch` in environments that host L402-gated APIs.
 */

import { L402Engine, agentPayer, type FetcherFn, type L402Config } from "./l402.js";
import type { AgentLike } from "./l402.js";

// ---------------------------------------------------------------------------
// Low-level: adapt a global-fetch Response into the engine's FetcherFn tuple
// ---------------------------------------------------------------------------

function _headersToRecord(headers: Headers): Record<string, string> {
  const result: Record<string, string> = {};
  headers.forEach((value, key) => {
    result[key] = value;
  });
  return result;
}

async function _responseToTuple(
  res: Response,
): Promise<[number, Record<string, string>, string | Uint8Array]> {
  const headers = _headersToRecord(res.headers);
  const contentType = res.headers.get("content-type") ?? "";
  let body: string | Uint8Array;
  if (contentType.includes("text") || contentType.includes("json") || contentType.includes("xml")) {
    body = await res.text();
  } else {
    body = new Uint8Array(await res.arrayBuffer());
  }
  return [res.status, headers, body];
}

// ---------------------------------------------------------------------------
// fetchWithL402 — drop-in fetch wrapper
// ---------------------------------------------------------------------------

export interface FetchWithL402Options {
  /** The L402Engine to use for payment. */
  engine: L402Engine;
  /**
   * Amount in sats to pay (often the invoice is self-describing).
   * @default 1
   */
  sats?: number;
  /** Underlying fetch implementation (defaults to global fetch). */
  fetchImpl?: typeof fetch;
}

/**
 * Drop-in `fetch` replacement that transparently handles L402 payment flows.
 *
 * Usage:
 *   const res = await fetchWithL402("https://api.example.com/paid-resource", {
 *     engine: myEngine,
 *     sats: 100,
 *   });
 */
export async function fetchWithL402(
  input: string | URL | Request,
  init: RequestInit & FetchWithL402Options,
): Promise<Response> {
  const { engine, sats = 1, fetchImpl = fetch, ...fetchInit } = init;

  const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
  const method = (fetchInit.method ?? "GET").toUpperCase();

  // Build an engine-compatible FetcherFn that wraps the underlying fetch.
  const fetcher: FetcherFn = async (
    fetchUrl: string,
    fetchMethod: string,
    extraHeaders: Record<string, string>,
    body?: string | Uint8Array | null,
  ) => {
    const merged = new Headers(fetchInit.headers);
    for (const [k, v] of Object.entries(extraHeaders)) {
      merged.set(k, v);
    }

    const res = await fetchImpl(fetchUrl, {
      ...fetchInit,
      method: fetchMethod,
      headers: merged,
      body: body ?? fetchInit.body,
    } as RequestInit);

    return _responseToTuple(res);
  };

  // Determine the body from the original init (engine passes it through).
  let bodyArg: string | Uint8Array | null = null;
  if (fetchInit.body != null) {
    if (typeof fetchInit.body === "string") {
      bodyArg = fetchInit.body;
    } else if (fetchInit.body instanceof Uint8Array) {
      bodyArg = fetchInit.body;
    } else if (fetchInit.body instanceof ArrayBuffer) {
      bodyArg = new Uint8Array(fetchInit.body);
    }
    // Other BodyInit types (FormData, URLSearchParams, ReadableStream) are passed
    // through as-is on the underlying fetch; body is null for engine tracking.
  }

  const result = await engine.fetchPaid(url, fetcher, {
    sats,
    method,
    headers: {},
    body: bodyArg,
  });

  // Reconstruct a Response from the FetchResult. A Uint8Array is a valid body
  // at runtime; the cast sidesteps the lib.dom ArrayBufferLike generic friction.
  const responseBody = result.body as BodyInit;
  return new Response(responseBody, {
    status: result.status,
    headers: result.headers,
  });
}

// ---------------------------------------------------------------------------
// Convenience: create a fetchWithL402-backed fetch from an Agent directly
// ---------------------------------------------------------------------------

/**
 * Create a fetch-compatible function pre-wired to a Conduit Agent for L402 payments.
 *
 * Usage:
 *   import { createAgentFetch } from "@conduit-btc/sdk";
 *   const fetch402 = createAgentFetch(myAgent, { maxAutoPaySats: 5000 });
 *   const res = await fetch402("https://api.example.com/paid", { sats: 100 });
 */
export function createAgentFetch(
  agent: AgentLike,
  config?: L402Config,
): (input: string | URL | Request, init?: RequestInit & { sats?: number }) => Promise<Response> {
  const engine = new L402Engine(agentPayer(agent), config);
  return (input, init = {}) =>
    fetchWithL402(input, { ...init, engine, sats: (init as { sats?: number }).sats ?? 1 });
}
