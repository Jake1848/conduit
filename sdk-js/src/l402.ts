/**
 * L402 payment-channel engine for the Conduit SDK (TypeScript port of sdk-python/conduit/l402.py).
 *
 * Public API
 * ----------
 * Typical usage:
 *
 *   import { L402Engine, L402Config, agentPayer } from "@conduit-btc/sdk";
 *
 *   const engine = new L402Engine(agentPayer(myAgent), { maxAutoPaySats: 5000 });
 *
 *   // On a 402 response:
 *   const authHeader = await engine.handleChallenge(
 *     "https://api.example.com/resource",
 *     response.headers.get("WWW-Authenticate") ?? "",
 *   );
 *   // Then replay with Authorization: <authHeader>
 *
 *   // Or use the full interceptor pattern:
 *   const result = await engine.fetchPaid("https://api.example.com/resource", myFetcher);
 *
 * Design notes
 * ------------
 * - HTTP-client-agnostic: callers supply a fetcher callable.
 * - Token cache keyed on MACAROON SCOPE (service identifier + capability caveats),
 *   NOT origin+URL. One macaroon authorising a whole service is reused across all
 *   paths without re-paying.
 * - Caveats re-validated before every reuse: expiry, capability, quota.
 * - Post-pay 402 guard: SAME vs NEW challenge classification with per-window cap.
 * - Guards run in order BEFORE paying: domain → sats-cap → approval-callback.
 *
 * Macaroon parsing
 * ----------------
 * No external macaroon library is used. The `macaroon` npm package lacks TypeScript
 * types, ships heavyweight crypto deps (sjcl, tweetnacl), and has no ESM export —
 * incompatible with this package's strict ESM+tsc setup. Instead, a minimal
 * libmacaroon v1 binary TLV decoder is implemented inline (see _parseMacaroonCaveats).
 * It decodes only what the engine needs: first-party caveat identifiers. Signature
 * verification is not performed (the server does that); we are a client-side token
 * cache, not an authorisation verifier.
 */

// ---------------------------------------------------------------------------
// Typed errors
// ---------------------------------------------------------------------------

export class L402Error extends Error {
  constructor(message: string) {
    super(message);
    this.name = "L402Error";
  }
}

/** The WWW-Authenticate header could not be parsed as a valid L402 challenge. */
export class InvalidChallenge extends L402Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidChallenge";
  }
}

/** The WWW-Authenticate header carries a recognised but unimplemented scheme. */
export class UnsupportedChallenge extends L402Error {
  constructor(message: string) {
    super(message);
    this.name = "UnsupportedChallenge";
  }
}

/** The engine refused to pay — domain blocked, sats cap exceeded, or approval denied. */
export class PaymentRejected extends L402Error {
  constructor(message: string) {
    super(message);
    this.name = "PaymentRejected";
  }
}

/** A post-pay 402 on the same resource has exceeded the per-window re-pay cap. */
export class RepayCapExceeded extends L402Error {
  constructor(message: string) {
    super(message);
    this.name = "RepayCapExceeded";
  }
}

/** Payment settled but the payer returned no preimage (or a faulted one). */
export class PreimageError extends L402Error {
  constructor(message: string) {
    super(message);
    this.name = "PreimageError";
  }
}

// ---------------------------------------------------------------------------
// Protocol detection
// ---------------------------------------------------------------------------

export type Protocol = "L402" | "LSAT";

// ---------------------------------------------------------------------------
// Data containers
// ---------------------------------------------------------------------------

/** What the caller's payer callable must return. */
export interface PaidResult {
  preimage: string | null | undefined;
  preimageError?: string | null;
}

/** Parsed result of a WWW-Authenticate: L402/LSAT header. */
export interface ParsedChallenge {
  protocol: Protocol;
  /** Raw base64 string from the header. */
  macaroonB64: string;
  /** BOLT11 invoice string. */
  invoice: string;
  /** Parsed scope fields extracted from caveats (may be empty). */
  scope: Record<string, string>;
  /** The canonical scope key used for cache lookups. */
  scopeKey: string;
}

/** A cached L402 credential, ready to replay as an Authorization header. */
export interface CachedToken {
  /** "L402 <macaroon>:<preimage>" */
  authHeader: string;
  macaroonB64: string;
  preimage: string;
  scopeKey: string;
  scope: Record<string, string>;
  paidSats: number;
  acquiredAt: number;
}

/** Return value from engine.fetchPaid. */
export interface FetchResult {
  status: number;
  body: string | Uint8Array;
  headers: Record<string, string>;
  paidSats: number;
  cached: boolean;
  preimageUsed: string | null;
}

// ---------------------------------------------------------------------------
// Payer callable type
// ---------------------------------------------------------------------------

export type PayInvoiceFn = (invoice: string, sats: number) => PaidResult | Promise<PaidResult>;

// ---------------------------------------------------------------------------
// Config / guards
// ---------------------------------------------------------------------------

export interface L402Config {
  maxAutoPaySats?: number | null;
  allowedDomains?: string[] | null;
  deniedDomains?: string[] | null;
  /** Called before paying. Return true to approve over-cap payment. */
  approve?: ((challenge: ParsedChallenge) => boolean) | null;
  /** How many new-challenge re-pays are allowed per fetchPaid cycle. Default 1. */
  maxRepaysPerResourceWindow?: number;
  /** Audit sink — receives a dict for every engine decision. Must not throw. */
  audit?: ((event: Record<string, unknown>) => void) | null;
}

// ---------------------------------------------------------------------------
// Minimal macaroon v1 binary TLV decoder
// ---------------------------------------------------------------------------
// Macaroon v1 serialisation (libmacaroon spec):
//   - Base64url-encoded binary.
//   - Binary consists of TLV packets, each: <field_id:VarInt> <length:VarInt> <data:bytes>
//     OR the simpler fixed-prefix scheme used by pymacaroons v1:
//       Each packet = 4-byte hex length (total packet length as ASCII hex) + data + \n
//       Field identifiers are ASCII strings preceding a space inside the data.
//
// pymacaroons serialises as: len(4 hex chars)|field SP value\n  ...  EOS
// e.g. "0020location https://example.com\n"
//       0020 = 32 decimal = len("location https://example.com\n") + 4
//
// First-party caveat field id = "cid"
// Third-party location = "cl", vid = "cv", cid = "cid"
// We only need "cid" packets whose data does NOT have a corresponding "vid"
// (first-party = no vid/cl preceding its cid).
//
// Simpler approach that matches pymacaroons v1: decode the base64, scan all
// "cid" packets, and collect their string values. We skip cids immediately
// preceded by a "vid" (third-party marker). The raw cid bytes are the caveat
// identifier strings for first-party caveats.

const _PACKET_MAGIC = 4; // 4-char hex length prefix

function _decodeMacaroonCaveats(b64: string): string[] {
  // Accept both standard and URL-safe base64.
  let bin: Uint8Array;
  try {
    const padded = b64.replace(/-/g, "+").replace(/_/g, "/");
    const pad = (4 - (padded.length % 4)) % 4;
    const raw = atob(padded + "=".repeat(pad));
    bin = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bin[i] = raw.charCodeAt(i);
  } catch {
    return [];
  }

  const td = new TextDecoder("utf-8", { fatal: false });
  const caveats: string[] = [];
  let pos = 0;
  let lastFieldWasVid = false;

  while (pos + _PACKET_MAGIC < bin.length) {
    // Read 4-byte hex length header.
    const lenHex = td.decode(bin.slice(pos, pos + _PACKET_MAGIC));
    const totalLen = parseInt(lenHex, 16);
    if (!Number.isFinite(totalLen) || totalLen < _PACKET_MAGIC) break;
    if (pos + totalLen > bin.length) break;

    // Data = bytes after the 4-char hex length, up to (but not including) the
    // trailing newline. Strip leading/trailing whitespace for safety.
    const data = bin.slice(pos + _PACKET_MAGIC, pos + totalLen);
    // Remove trailing newline.
    const dataStr = td.decode(data.at(-1) === 0x0a ? data.slice(0, -1) : data);

    // Identify field by the first space separator.
    const spIdx = dataStr.indexOf(" ");
    if (spIdx > 0) {
      const field = dataStr.slice(0, spIdx);
      const value = dataStr.slice(spIdx + 1);

      if (field === "vid") {
        lastFieldWasVid = true;
      } else if (field === "cid") {
        if (!lastFieldWasVid) {
          caveats.push(value);
        }
        lastFieldWasVid = false;
      } else if (field === "cl") {
        // third-party location — ignore but reset flag
        lastFieldWasVid = false;
      } else {
        lastFieldWasVid = false;
      }
    } else {
      lastFieldWasVid = false;
    }

    pos += totalLen;
  }

  return caveats;
}

// ---------------------------------------------------------------------------
// Caveat parsing helpers
// ---------------------------------------------------------------------------

const _CAVEAT_RE = /^([^=]+)=(.*)$/;

function _parseCaveats(macaroonB64: string): Record<string, string> {
  const result: Record<string, string> = {};
  const caveats = _decodeMacaroonCaveats(macaroonB64);
  for (const identifier of caveats) {
    const m = _CAVEAT_RE.exec(identifier.trim());
    if (m) {
      const key = m[1].trim().toLowerCase();
      const val = m[2].trim();
      result[key] = val;
    }
  }
  return result;
}

/** Extract the macaroon identifier (location+id) for fallback cache key. */
function _macaroonIdentifier(b64: string): string {
  let bin: Uint8Array;
  try {
    const padded = b64.replace(/-/g, "+").replace(/_/g, "/");
    const pad = (4 - (padded.length % 4)) % 4;
    const raw = atob(padded + "=".repeat(pad));
    bin = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) bin[i] = raw.charCodeAt(i);
  } catch {
    return b64.slice(0, 64);
  }

  const td = new TextDecoder("utf-8", { fatal: false });
  let pos = 0;
  while (pos + _PACKET_MAGIC < bin.length) {
    const lenHex = td.decode(bin.slice(pos, pos + _PACKET_MAGIC));
    const totalLen = parseInt(lenHex, 16);
    if (!Number.isFinite(totalLen) || totalLen < _PACKET_MAGIC) break;
    if (pos + totalLen > bin.length) break;

    const data = bin.slice(pos + _PACKET_MAGIC, pos + totalLen);
    const dataStr = td.decode(data.at(-1) === 0x0a ? data.slice(0, -1) : data);
    const spIdx = dataStr.indexOf(" ");
    if (spIdx > 0 && dataStr.slice(0, spIdx) === "identifier") {
      return dataStr.slice(spIdx + 1);
    }
    pos += totalLen;
  }
  return b64.slice(0, 64);
}

function _scopeKeyFromCaveats(macaroonB64: string, caveats: Record<string, string>): string {
  if ("services" in caveats) {
    const services = caveats["services"]
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .sort()
      .join(",");
    const caps = caveats["capabilities"] ?? "";
    if (caps) {
      const capsNorm = caps
        .split(",")
        .map((c) => c.trim().toLowerCase())
        .sort()
        .join(",");
      return `svc:${services}|caps:${capsNorm}`;
    }
    return `svc:${services}`;
  }
  // Fall back to the macaroon identifier.
  const identifier = _macaroonIdentifier(macaroonB64);
  if (identifier) return `mac:${identifier}`;
  return `raw:${macaroonB64.slice(0, 64)}`;
}

function _caveatStillValid(scope: Record<string, string>): { ok: boolean; reason: string } {
  // Expiry check
  if ("valid_until" in scope) {
    const val = scope["valid_until"].trim();
    let expiry: number | null = null;
    const asNum = Number(val);
    if (!isNaN(asNum) && val !== "") {
      expiry = asNum;
    } else {
      // ISO-8601 / RFC-3339
      try {
        const normalized = val.replace(/Z$/, "+00:00");
        const ts = Date.parse(normalized);
        if (!isNaN(ts)) expiry = ts / 1000;
      } catch {
        // unknown format — don't block reuse
      }
    }
    if (expiry !== null && Date.now() / 1000 >= expiry) {
      return { ok: false, reason: "token expired (valid_until)" };
    }
  }

  // Quota / count check
  if ("count" in scope) {
    const count = parseInt(scope["count"], 10);
    if (!isNaN(count) && count <= 0) {
      return { ok: false, reason: "token quota exhausted (count≤0)" };
    }
  }

  return { ok: true, reason: "" };
}

// ---------------------------------------------------------------------------
// Header parsing
// ---------------------------------------------------------------------------

// Both "L402" and "LSAT" schemes use the same header format.
const _HEADER_SCHEME_RE =
  /^(?:L402|LSAT)\s+macaroon\s*=\s*"([^"]+)".*?invoice\s*=\s*"([^"]+)"/i;
const _HEADER_SCHEME_RE_ALT =
  /^(?:L402|LSAT)\s+invoice\s*=\s*"([^"]+)".*?macaroon\s*=\s*"([^"]+)"/i;

function _detectProtocol(wwwAuthenticate: string): Protocol {
  const header = wwwAuthenticate.trim();
  const firstToken = header.split(/\s/)[0]?.toUpperCase() ?? "";
  if (firstToken === "L402" || firstToken === "LSAT") {
    return firstToken as Protocol;
  }
  throw new UnsupportedChallenge(
    `WWW-Authenticate scheme ${JSON.stringify(firstToken)} is not supported by this engine. ` +
      "Only L402 (and legacy LSAT) challenges are implemented.",
  );
}

export function parseChallenge(wwwAuthenticate: string): ParsedChallenge {
  const protocol = _detectProtocol(wwwAuthenticate);

  let macaroonB64: string;
  let invoice: string;

  const m1 = _HEADER_SCHEME_RE.exec(wwwAuthenticate);
  if (m1) {
    macaroonB64 = m1[1].trim();
    invoice = m1[2].trim();
  } else {
    const m2 = _HEADER_SCHEME_RE_ALT.exec(wwwAuthenticate);
    if (m2) {
      invoice = m2[1].trim();
      macaroonB64 = m2[2].trim();
    } else {
      throw new InvalidChallenge(
        `Could not parse ${protocol} challenge from WWW-Authenticate header. ` +
          `Expected: macaroon="<base64>" and invoice="<bolt11>"`,
      );
    }
  }

  if (!macaroonB64) throw new InvalidChallenge("L402 challenge contains empty macaroon field.");
  if (!invoice) throw new InvalidChallenge("L402 challenge contains empty invoice field.");
  if (!invoice.toLowerCase().startsWith("ln") && !invoice.includes(":")) {
    throw new InvalidChallenge(
      `L402 challenge invoice does not look like a BOLT11 string: ${JSON.stringify(invoice.slice(0, 40))}`,
    );
  }

  // Decode caveats (best-effort — fall back to raw-key on failure).
  let scope: Record<string, string> = {};
  let scopeKey: string;
  try {
    scope = _parseCaveats(macaroonB64);
    scopeKey = _scopeKeyFromCaveats(macaroonB64, scope);
  } catch {
    scopeKey = `raw:${macaroonB64.slice(0, 64)}`;
  }
  // If caveats are empty (non-decodable binary or no caveats), scopeKey may
  // have been set to mac:<identifier> which is fine. But if _parseCaveats
  // returned empty AND _scopeKeyFromCaveats also couldn't extract identifier,
  // raw: fallback is already set.
  if (!scopeKey) scopeKey = `raw:${macaroonB64.slice(0, 64)}`;

  return { protocol, macaroonB64, invoice, scope, scopeKey };
}

// ---------------------------------------------------------------------------
// Token store (pluggable)
// ---------------------------------------------------------------------------

export interface ITokenStore {
  get(scopeKey: string): CachedToken | undefined;
  set(token: CachedToken): void;
  delete(scopeKey: string): void;
  clear(): void;
}

export class MemoryTokenStore implements ITokenStore {
  private _store = new Map<string, CachedToken>();

  get(scopeKey: string): CachedToken | undefined {
    return this._store.get(scopeKey);
  }
  set(token: CachedToken): void {
    this._store.set(token.scopeKey, token);
  }
  delete(scopeKey: string): void {
    this._store.delete(scopeKey);
  }
  clear(): void {
    this._store.clear();
  }
}

// ---------------------------------------------------------------------------
// Re-pay guard state (per resource URL, per window)
// ---------------------------------------------------------------------------

interface RepayRecord {
  count: number;
  lastChallengeFingerprint: string;
}

// ---------------------------------------------------------------------------
// Fetcher type
// ---------------------------------------------------------------------------

export type FetcherFn = (
  url: string,
  method: string,
  headers: Record<string, string>,
  body?: string | Uint8Array | null,
) => Promise<[number, Record<string, string>, string | Uint8Array]>;

// ---------------------------------------------------------------------------
// Main engine
// ---------------------------------------------------------------------------

interface ResolvedConfig {
  maxAutoPaySats: number | null;
  allowedDomains: string[] | null;
  deniedDomains: string[] | null;
  approve: ((challenge: ParsedChallenge) => boolean) | null;
  maxRepaysPerResourceWindow: number;
  audit: ((event: Record<string, unknown>) => void) | null;
}

export class L402Engine {
  private _payInvoice: PayInvoiceFn;
  private _config: ResolvedConfig;
  private _store: ITokenStore;
  private _repay = new Map<string, RepayRecord>();

  constructor(payInvoice: PayInvoiceFn, config?: L402Config, store?: ITokenStore) {
    this._payInvoice = payInvoice;
    this._config = {
      maxAutoPaySats: config?.maxAutoPaySats ?? null,
      allowedDomains: config?.allowedDomains ?? null,
      deniedDomains: config?.deniedDomains ?? null,
      approve: config?.approve ?? null,
      maxRepaysPerResourceWindow: config?.maxRepaysPerResourceWindow ?? 1,
      audit: config?.audit ?? null,
    };
    this._store = store ?? new MemoryTokenStore();
  }

  // ------------------------------------------------------------------
  // Public: handle a 402 challenge and return an Authorization header
  // ------------------------------------------------------------------

  async handleChallenge(url: string, wwwAuthenticate: string, sats = 1): Promise<string> {
    const challenge = parseChallenge(wwwAuthenticate);
    this._audit("challenge_parsed", { url, scopeKey: challenge.scopeKey });

    // 1. Guard: domain check
    this._guardDomain(url, challenge);

    // 2. Cache lookup
    const cached = this._store.get(challenge.scopeKey);
    if (cached !== undefined) {
      const { ok, reason } = _caveatStillValid(cached.scope);
      if (ok) {
        this._audit("cache_hit", { url, scopeKey: challenge.scopeKey });
        return cached.authHeader;
      } else {
        this._audit("cache_miss_stale", { url, scopeKey: challenge.scopeKey, reason });
        this._store.delete(challenge.scopeKey);
      }
    }

    // 3. Guard: sats cap + approval
    this._guardCapAndApproval(url, challenge, sats);

    // 4. Pay
    this._audit("paying", { url, scopeKey: challenge.scopeKey, sats });
    const result = await this._payInvoice(challenge.invoice, sats);
    this._checkPreimage(result);

    const authHeader = `L402 ${challenge.macaroonB64}:${result.preimage}`;
    const token: CachedToken = {
      authHeader,
      macaroonB64: challenge.macaroonB64,
      preimage: result.preimage as string,
      scopeKey: challenge.scopeKey,
      scope: challenge.scope,
      paidSats: sats,
      acquiredAt: Date.now(),
    };
    this._store.set(token);
    this._audit("paid", { url, scopeKey: challenge.scopeKey, sats });
    return authHeader;
  }

  // ------------------------------------------------------------------
  // Public: full interceptor — fetch, 402-detect, pay, replay
  // ------------------------------------------------------------------

  async fetchPaid(
    url: string,
    fetcher: FetcherFn,
    opts: {
      sats?: number;
      method?: string;
      headers?: Record<string, string>;
      body?: string | Uint8Array | null;
    } = {},
  ): Promise<FetchResult> {
    const { sats = 1, method = "GET", body = null } = opts;
    const requestHeaders = { ...(opts.headers ?? {}) };

    // The re-pay window is a SINGLE fetch cycle: each top-level fetchPaid call
    // gets a fresh re-pay budget for this URL. Without this reset the per-URL
    // counter would accumulate across independent calls and permanently refuse a
    // resource after its first lifetime re-pay. Within a cycle, runaway re-paying
    // is still bounded (at most one re-pay, then the status3===402 check raises).
    this._repay.delete(url);

    // --- First attempt ---
    const [status, respHeaders, respBody] = await fetcher(url, method, requestHeaders, body);

    if (status !== 402) {
      return { status, body: respBody, headers: respHeaders, paidSats: 0, cached: false, preimageUsed: null };
    }

    const wwwAuth =
      respHeaders["WWW-Authenticate"] ?? respHeaders["www-authenticate"] ?? "";
    if (!wwwAuth) {
      throw new InvalidChallenge("Server returned 402 with no WWW-Authenticate header.");
    }

    // Check if we have a cached token that covers this challenge's scope.
    const challenge = parseChallenge(wwwAuth);
    let cachedToken = this._store.get(challenge.scopeKey);
    let wasCached = false;
    let authValue = "";
    let paidSats = 0;
    let preimageUsed: string | null = null;

    if (cachedToken !== undefined) {
      const { ok } = _caveatStillValid(cachedToken.scope);
      if (ok) {
        wasCached = true;
        authValue = cachedToken.authHeader;
        paidSats = 0;
        preimageUsed = cachedToken.preimage;
      } else {
        this._store.delete(challenge.scopeKey);
        cachedToken = undefined;
      }
    }

    if (!wasCached) {
      // Pay for the first time (guards run inside handleChallenge)
      authValue = await this.handleChallenge(url, wwwAuth, sats);
      const cachedNow = this._store.get(challenge.scopeKey);
      paidSats = sats;
      preimageUsed = cachedNow?.preimage ?? null;
    }

    // --- Replay with Authorization ---
    requestHeaders["Authorization"] = authValue;
    const [status2, respHeaders2, respBody2] = await fetcher(url, method, requestHeaders, body);

    if (status2 !== 402) {
      return {
        status: status2,
        body: respBody2,
        headers: respHeaders2,
        paidSats: wasCached ? 0 : paidSats,
        cached: wasCached,
        preimageUsed,
      };
    }

    // --- Post-pay 402: classify SAME vs NEW challenge ---
    const wwwAuth2 =
      respHeaders2["WWW-Authenticate"] ?? respHeaders2["www-authenticate"] ?? "";
    this._handlePostPay402(url, wwwAuth, wwwAuth2);

    // We got here: new challenge, within re-pay cap — pay again.
    const authValue2 = await this.handleChallenge(url, wwwAuth2, sats);
    const cachedNow2 = this._store.get(parseChallenge(wwwAuth2).scopeKey);
    const preimageUsed2 = cachedNow2?.preimage ?? null;

    requestHeaders["Authorization"] = authValue2;
    const [status3, respHeaders3, respBody3] = await fetcher(url, method, requestHeaders, body);

    if (status3 === 402) {
      throw new RepayCapExceeded(
        `Resource at ${JSON.stringify(url)} returned 402 three times in one fetch cycle. ` +
          "Refusing to continue to avoid runaway spending.",
      );
    }

    return {
      status: status3,
      body: respBody3,
      headers: respHeaders3,
      paidSats: paidSats + sats,
      cached: false,
      preimageUsed: preimageUsed2,
    };
  }

  // ------------------------------------------------------------------
  // Post-pay 402 classification
  // ------------------------------------------------------------------

  private _handlePostPay402(url: string, originalWwwAuth: string, newWwwAuth: string): void {
    const orig = parseChallenge(originalWwwAuth);
    const next = parseChallenge(newWwwAuth);

    const origFp = `${orig.macaroonB64}|${orig.invoice}`;
    const newFp = `${next.macaroonB64}|${next.invoice}`;

    if (origFp === newFp) {
      this._audit("post_pay_same_challenge", { url });
      throw new RepayCapExceeded(
        `Post-pay 402 on ${JSON.stringify(url)} carried the SAME challenge (same macaroon ` +
          "and invoice) as the one just paid. This indicates the token was rejected server-side " +
          "(clock skew? revoked?). Refusing to re-pay the same invoice to avoid a double-spend.",
      );
    }

    // NEW challenge — check re-pay cap.
    let rec = this._repay.get(url);
    if (!rec) {
      rec = { count: 0, lastChallengeFingerprint: "" };
      this._repay.set(url, rec);
    }
    rec.count += 1;
    rec.lastChallengeFingerprint = newFp;

    const cap = this._config.maxRepaysPerResourceWindow;
    if (rec.count > cap) {
      this._audit("repay_cap_exceeded", { url, count: rec.count, cap });
      throw new RepayCapExceeded(
        `Resource at ${JSON.stringify(url)} has triggered ${rec.count} re-pays in the current ` +
          `window, exceeding the cap of ${cap}. Refusing to continue.`,
      );
    }

    this._audit("post_pay_new_challenge", { url, count: rec.count, cap });
  }

  // ------------------------------------------------------------------
  // Guards
  // ------------------------------------------------------------------

  private _guardDomain(url: string, _challenge: ParsedChallenge): void {
    const cfg = this._config;
    if (!cfg.deniedDomains && !cfg.allowedDomains) return;

    let host = "";
    try {
      host = new URL(url).hostname ?? "";
    } catch {
      host = "";
    }

    if (cfg.deniedDomains) {
      for (const pattern of cfg.deniedDomains) {
        if (host === pattern || host.endsWith("." + pattern)) {
          this._audit("refused_denied_domain", { url, host, pattern });
          throw new PaymentRejected(
            `Domain ${JSON.stringify(host)} is in the deniedDomains list. Payment refused.`,
          );
        }
      }
    }

    if (cfg.allowedDomains) {
      const allowed = cfg.allowedDomains.some(
        (p) => host === p || host.endsWith("." + p),
      );
      if (!allowed) {
        this._audit("refused_not_in_allowed_domains", { url, host });
        throw new PaymentRejected(
          `Domain ${JSON.stringify(host)} is not in the allowedDomains list. Payment refused.`,
        );
      }
    }
  }

  private _guardCapAndApproval(url: string, challenge: ParsedChallenge, sats: number): void {
    const cfg = this._config;
    if (cfg.maxAutoPaySats != null && sats > cfg.maxAutoPaySats) {
      if (cfg.approve != null && cfg.approve(challenge)) {
        this._audit("approved_over_cap", { url, sats, cap: cfg.maxAutoPaySats });
        return;
      }
      this._audit("refused_over_cap", { url, sats, cap: cfg.maxAutoPaySats });
      throw new PaymentRejected(
        `Payment of ${sats} sats exceeds maxAutoPaySats=${cfg.maxAutoPaySats}. ` +
          "Payment refused. Supply an `approve` callback to override.",
      );
    }
  }

  // ------------------------------------------------------------------
  // Preimage validation
  // ------------------------------------------------------------------

  private _checkPreimage(result: PaidResult): void {
    if (result.preimageError) {
      throw new PreimageError(
        `Payer returned a preimageError: ${JSON.stringify(result.preimageError)}. ` +
          "Cannot build an L402 Authorization header without a valid preimage.",
      );
    }
    if (!result.preimage) {
      throw new PreimageError(
        "Payer returned no preimage (null/empty). " +
          "Cannot build an L402 Authorization header without a preimage. " +
          "Ensure the Conduit pay endpoint returns a preimage " +
          "(requires write-scoped API key and a settled payment).",
      );
    }
  }

  // ------------------------------------------------------------------
  // Audit sink
  // ------------------------------------------------------------------

  private _audit(event: string, extra: Record<string, unknown> = {}): void {
    if (this._config.audit != null) {
      try {
        this._config.audit({ event, ...extra });
      } catch {
        // audit errors must never break the payment path
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Convenience: build a payer callable from a conduit.Agent
// ---------------------------------------------------------------------------

/** Minimal interface for any object that has a .pay() method. */
export interface AgentLike {
  pay(opts: { to: string; sats: number }): Promise<{ preimage?: string | null; preimageError?: string | null }>;
}

/**
 * Build a PayInvoiceFn wrapping a Conduit Agent (or any object with .pay()).
 *
 * Usage:
 *   import { Agent } from "@conduit-btc/sdk";
 *   import { L402Engine, agentPayer } from "@conduit-btc/sdk";
 *   const engine = new L402Engine(agentPayer(myAgent));
 */
export function agentPayer(agent: AgentLike): PayInvoiceFn {
  return async (invoice: string, sats: number): Promise<PaidResult> => {
    const receipt = await agent.pay({ to: invoice, sats });
    return {
      preimage: receipt.preimage ?? null,
      preimageError: receipt.preimageError ?? null,
    };
  };
}

// ---------------------------------------------------------------------------
// Re-exports (internal helpers exposed for testing)
// ---------------------------------------------------------------------------

export { _caveatStillValid, _parseCaveats, _decodeMacaroonCaveats, _scopeKeyFromCaveats };
