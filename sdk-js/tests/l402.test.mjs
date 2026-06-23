/**
 * L402 engine decision-parity tests.
 * Mirrors the Python test suite: parse + invalid, unsupported, happy-path,
 * cache scope reuse, expired caveat, capability bypass, re-pay guard,
 * same-challenge guard, re-pay window reset, guards, null/faulted preimage.
 *
 * Run: tsc && node --test tests/l402.test.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  L402Engine,
  MemoryTokenStore,
  parseChallenge,
  agentPayer,
  InvalidChallenge,
  UnsupportedChallenge,
  PaymentRejected,
  RepayCapExceeded,
  PreimageError,
} from "../dist/index.js";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

/**
 * Build a minimal pymacaroons-v1-compatible binary macaroon serialised as base64.
 * This replicates the wire format: each packet = 4-hex-char-length + "field value\n"
 * We include an "identifier" field plus optional "cid" (first-party caveat) packets.
 */
function buildMacaroonB64(identifier, caveats = []) {
  function packet(field, value) {
    const content = `${field} ${value}\n`;
    const totalLen = 4 + content.length; // 4-char hex prefix + content
    const hexLen = totalLen.toString(16).padStart(4, "0");
    return hexLen + content;
  }

  let raw = "";
  raw += packet("location", "https://test.example.com");
  raw += packet("identifier", identifier);
  for (const c of caveats) {
    raw += packet("cid", c);
  }
  // signature placeholder (32 zero bytes encoded as 4+4+64 hex chars)
  const sigField = "signature ";
  const sigBytes = "\x00".repeat(32);
  const sigContent = sigField + sigBytes + "\n";
  const sigLen = (4 + sigContent.length).toString(16).padStart(4, "0");
  raw += sigLen + sigContent;

  // Encode as base64url (no padding) — pymacaroons uses standard base64
  const encoded = btoa(raw);
  return encoded;
}

function makeChallenge(macaroonB64, invoice, scheme = "L402") {
  return `${scheme} macaroon="${macaroonB64}", invoice="${invoice}"`;
}

const VALID_INVOICE = "lnbc100n1example_invoice_string";

function stubPayer(preimage = "aabbccdd", preimageError = null) {
  return (_invoice, _sats) => ({ preimage, preimageError });
}

function nullPayer() {
  return (_invoice, _sats) => ({ preimage: null, preimageError: null });
}

function faultedPayer(errorMsg) {
  return (_invoice, _sats) => ({ preimage: null, preimageError: errorMsg });
}

// Build a fetcher that sequences through a list of [status, headers, body] responses.
function makeFetcher(responses) {
  let i = 0;
  return async (_url, _method, _headers, _body) => {
    const r = responses[i++] ?? responses.at(-1);
    return [r.status, r.headers ?? {}, r.body ?? ""];
  };
}

// ---------------------------------------------------------------------------
// 1. Header parsing — L402 and LSAT schemes, both field orderings
// ---------------------------------------------------------------------------

test("parse: L402 macaroon-first order", () => {
  const mac = buildMacaroonB64("test-id-1");
  const ch = parseChallenge(makeChallenge(mac, VALID_INVOICE));
  assert.equal(ch.protocol, "L402");
  assert.equal(ch.macaroonB64, mac);
  assert.equal(ch.invoice, VALID_INVOICE);
  assert.ok(ch.scopeKey.length > 0);
});

test("parse: LSAT legacy scheme accepted", () => {
  const mac = buildMacaroonB64("test-id-2");
  const ch = parseChallenge(makeChallenge(mac, VALID_INVOICE, "LSAT"));
  assert.equal(ch.protocol, "LSAT");
  assert.equal(ch.macaroonB64, mac);
});

test("parse: invoice-first field order", () => {
  const mac = buildMacaroonB64("test-id-3");
  const header = `L402 invoice="${VALID_INVOICE}", macaroon="${mac}"`;
  const ch = parseChallenge(header);
  assert.equal(ch.macaroonB64, mac);
  assert.equal(ch.invoice, VALID_INVOICE);
});

test("parse: caveats extracted — services + capabilities → scope key", () => {
  const mac = buildMacaroonB64("test-id-4", [
    "services=loop, lnd",
    "capabilities=loop:read,loop:write",
  ]);
  const ch = parseChallenge(makeChallenge(mac, VALID_INVOICE));
  assert.equal(ch.scope["services"], "loop, lnd");
  assert.equal(ch.scope["capabilities"], "loop:read,loop:write");
  // Scope key should be services-based, normalised + sorted
  assert.ok(ch.scopeKey.startsWith("svc:"), `scopeKey should start with svc: but got: ${ch.scopeKey}`);
  assert.ok(ch.scopeKey.includes("lnd"), "scopeKey should include lnd");
  assert.ok(ch.scopeKey.includes("loop"), "scopeKey should include loop");
});

test("parse: valid_until caveat present in scope", () => {
  const mac = buildMacaroonB64("test-id-5", [
    "valid_until=9999999999",
  ]);
  const ch = parseChallenge(makeChallenge(mac, VALID_INVOICE));
  assert.equal(ch.scope["valid_until"], "9999999999");
});

// ---------------------------------------------------------------------------
// 2. InvalidChallenge — malformed headers
// ---------------------------------------------------------------------------

test("InvalidChallenge: missing invoice field", () => {
  const mac = buildMacaroonB64("bad-id");
  assert.throws(
    () => parseChallenge(`L402 macaroon="${mac}"`),
    InvalidChallenge,
  );
});

test("InvalidChallenge: missing macaroon field", () => {
  assert.throws(
    () => parseChallenge(`L402 invoice="${VALID_INVOICE}"`),
    InvalidChallenge,
  );
});

test("InvalidChallenge: invoice not bolt11-like", () => {
  const mac = buildMacaroonB64("bad-inv");
  assert.throws(
    () => parseChallenge(`L402 macaroon="${mac}", invoice="notaninvoice"`),
    InvalidChallenge,
  );
});

test("InvalidChallenge: empty macaroon value", () => {
  assert.throws(
    () => parseChallenge(`L402 macaroon="", invoice="${VALID_INVOICE}"`),
    InvalidChallenge,
  );
});

// ---------------------------------------------------------------------------
// 3. UnsupportedChallenge — unrecognised scheme
// ---------------------------------------------------------------------------

test("UnsupportedChallenge: Bearer scheme", () => {
  assert.throws(
    () => parseChallenge(`Bearer token="abc123"`),
    UnsupportedChallenge,
  );
});

test("UnsupportedChallenge: empty header", () => {
  assert.throws(
    () => parseChallenge(""),
    UnsupportedChallenge,
  );
});

// ---------------------------------------------------------------------------
// 4. Happy-path: handleChallenge builds correct Authorization header
// ---------------------------------------------------------------------------

test("handleChallenge: returns L402 <mac>:<preimage>", async () => {
  const mac = buildMacaroonB64("happy-id");
  const engine = new L402Engine(stubPayer("preimage_hex_abc"));
  const header = await engine.handleChallenge(
    "https://api.example.com/resource",
    makeChallenge(mac, VALID_INVOICE),
    100,
  );
  assert.equal(header, `L402 ${mac}:preimage_hex_abc`);
});

// ---------------------------------------------------------------------------
// 5. Cache hit: same scope key → one pay, reuse on second call
// ---------------------------------------------------------------------------

test("cache: same scope key reused across paths — only one payment", async () => {
  const mac = buildMacaroonB64("cache-id", ["services=myservice"]);
  let payCount = 0;
  const payer = (_inv, _sats) => {
    payCount++;
    return { preimage: "cached_preimage", preimageError: null };
  };
  const engine = new L402Engine(payer);
  const url1 = "https://api.example.com/path1";
  const url2 = "https://api.example.com/path2";
  const header = makeChallenge(mac, VALID_INVOICE);

  const h1 = await engine.handleChallenge(url1, header, 1);
  const h2 = await engine.handleChallenge(url2, header, 1);

  assert.equal(payCount, 1, "should have paid only once");
  assert.equal(h1, h2, "both calls should return the same auth header");
});

// ---------------------------------------------------------------------------
// 6. Expired caveat → cache miss → re-pay
// ---------------------------------------------------------------------------

test("cache: expired valid_until triggers re-pay", async () => {
  const pastTs = Math.floor(Date.now() / 1000) - 3600; // 1 hour ago
  const mac = buildMacaroonB64("expired-id", [`valid_until=${pastTs}`]);
  let payCount = 0;
  const payer = (_inv, _sats) => {
    payCount++;
    return { preimage: `preimage_${payCount}`, preimageError: null };
  };
  const engine = new L402Engine(payer);
  const url = "https://api.example.com/resource";
  const header = makeChallenge(mac, VALID_INVOICE);

  await engine.handleChallenge(url, header, 1);
  assert.equal(payCount, 1);

  // Second call with same expired macaroon → cache miss → pay again
  await engine.handleChallenge(url, header, 1);
  assert.equal(payCount, 2, "expired token should trigger re-pay");
});

// ---------------------------------------------------------------------------
// 7. Capability / quota not covered → bypass cache (different scope key)
// ---------------------------------------------------------------------------

test("cache: different capability scope → separate cache entries, two payments", async () => {
  const mac1 = buildMacaroonB64("cap-id-1", [
    "services=myservice",
    "capabilities=read",
  ]);
  const mac2 = buildMacaroonB64("cap-id-2", [
    "services=myservice",
    "capabilities=write",
  ]);
  let payCount = 0;
  const payer = (_inv, _sats) => {
    payCount++;
    return { preimage: `p${payCount}`, preimageError: null };
  };
  const engine = new L402Engine(payer);
  const url = "https://api.example.com/resource";

  await engine.handleChallenge(url, makeChallenge(mac1, VALID_INVOICE), 1);
  await engine.handleChallenge(url, makeChallenge(mac2, VALID_INVOICE + "2"), 1);

  assert.equal(payCount, 2, "different capability scopes should each be paid");
});

// ---------------------------------------------------------------------------
// 8. Re-pay guard: NEW challenge within cap (one re-pay allowed)
// ---------------------------------------------------------------------------

test("fetchPaid: new challenge post-pay 402 → one re-pay allowed then RepayCapExceeded on third 402", async () => {
  const mac1 = buildMacaroonB64("repay-mac-1");
  const mac2 = buildMacaroonB64("repay-mac-2");
  const inv1 = "lnbc100n1invoice_one";
  const inv2 = "lnbc100n1invoice_two";

  let payCount = 0;
  const payer = (_inv, _sats) => {
    payCount++;
    return { preimage: `p${payCount}`, preimageError: null };
  };

  const engine = new L402Engine(payer, { maxRepaysPerResourceWindow: 1 });

  const fetcher = makeFetcher([
    // First attempt: 402 with challenge 1
    { status: 402, headers: { "WWW-Authenticate": makeChallenge(mac1, inv1) }, body: "" },
    // Replay with auth 1: still 402 with NEW challenge 2
    { status: 402, headers: { "WWW-Authenticate": makeChallenge(mac2, inv2) }, body: "" },
    // Replay with auth 2: still 402 (third 402 = RepayCapExceeded)
    { status: 402, headers: {}, body: "" },
  ]);

  await assert.rejects(
    () => engine.fetchPaid("https://api.example.com/r", fetcher, { sats: 1 }),
    RepayCapExceeded,
  );
  // Should have paid twice (once for each new challenge)
  assert.equal(payCount, 2, "should pay for each new challenge");
});

test("fetchPaid: new challenge post-pay 402 → one re-pay, then success", async () => {
  const mac1 = buildMacaroonB64("repay-ok-1");
  const mac2 = buildMacaroonB64("repay-ok-2");
  const inv1 = "lnbc100n1ok_invoice_one";
  const inv2 = "lnbc100n1ok_invoice_two";

  let payCount = 0;
  const payer = (_inv, _sats) => {
    payCount++;
    return { preimage: `px${payCount}`, preimageError: null };
  };

  const engine = new L402Engine(payer, { maxRepaysPerResourceWindow: 1 });

  const fetcher = makeFetcher([
    // First: 402 with challenge 1
    { status: 402, headers: { "WWW-Authenticate": makeChallenge(mac1, inv1) }, body: "" },
    // Replay 1: 402 with NEW challenge 2
    { status: 402, headers: { "WWW-Authenticate": makeChallenge(mac2, inv2) }, body: "" },
    // Replay 2: 200 OK
    { status: 200, headers: {}, body: "paid content" },
  ]);

  const result = await engine.fetchPaid("https://api.example.com/r", fetcher, { sats: 1 });
  assert.equal(result.status, 200);
  assert.equal(payCount, 2);
});

// ---------------------------------------------------------------------------
// 9. Re-pay guard: SAME challenge → no re-pay, raise immediately
// ---------------------------------------------------------------------------

test("fetchPaid: same challenge post-pay 402 → RepayCapExceeded (no re-pay)", async () => {
  const mac = buildMacaroonB64("same-mac");
  const inv = "lnbc100n1same_invoice";

  let payCount = 0;
  const payer = (_inv, _sats) => {
    payCount++;
    return { preimage: "p1", preimageError: null };
  };

  const engine = new L402Engine(payer);

  const fetcher = makeFetcher([
    // First: 402
    { status: 402, headers: { "WWW-Authenticate": makeChallenge(mac, inv) }, body: "" },
    // Replay: SAME 402 challenge
    { status: 402, headers: { "WWW-Authenticate": makeChallenge(mac, inv) }, body: "" },
  ]);

  await assert.rejects(
    () => engine.fetchPaid("https://api.example.com/r", fetcher, { sats: 1 }),
    RepayCapExceeded,
  );
  assert.equal(payCount, 1, "should not re-pay on same challenge");
});

// ---------------------------------------------------------------------------
// 10. Re-pay window resets across two fetchPaid calls
// ---------------------------------------------------------------------------

test("fetchPaid: re-pay window resets per fetchPaid call", async () => {
  // On the first fetchPaid cycle: pay challenge A, get 402 B (new), pay B,
  // third 402 → RepayCapExceeded.
  // On the SECOND fetchPaid call to the same URL: the window should reset,
  // so challenge B → pay → success (no RepayCapExceeded).

  const macA = buildMacaroonB64("window-mac-a");
  const macB = buildMacaroonB64("window-mac-b");
  const invA = "lnbc100n1window_inv_a";
  const invB = "lnbc100n1window_inv_b";

  let payCount = 0;
  const payer = (_inv, _sats) => {
    payCount++;
    return { preimage: `pw${payCount}`, preimageError: null };
  };

  const engine = new L402Engine(payer, { maxRepaysPerResourceWindow: 1 });
  const url = "https://api.example.com/windowed";

  // First call: A → pay A → 402 B (new) → pay B → 402 again → RepayCapExceeded
  const fetcher1 = makeFetcher([
    { status: 402, headers: { "WWW-Authenticate": makeChallenge(macA, invA) }, body: "" },
    { status: 402, headers: { "WWW-Authenticate": makeChallenge(macB, invB) }, body: "" },
    { status: 402, headers: {}, body: "" },
  ]);
  await assert.rejects(
    () => engine.fetchPaid(url, fetcher1, { sats: 1 }),
    RepayCapExceeded,
  );
  assert.equal(payCount, 2);

  // Second call to SAME url: window should be reset.
  // Server now accepts payment for macB (already cached from cycle 1, still valid).
  // So the engine should return cached token and succeed.
  const fetcher2 = makeFetcher([
    // Server returns 402 with macB again (cached, valid) → engine replays → 200
    { status: 402, headers: { "WWW-Authenticate": makeChallenge(macB, invB) }, body: "" },
    { status: 200, headers: {}, body: "ok second call" },
  ]);

  const result2 = await engine.fetchPaid(url, fetcher2, { sats: 1 });
  assert.equal(result2.status, 200, "second fetchPaid call should succeed after window reset");
  // payCount should still be 2 (cache hit for macB)
  assert.equal(payCount, 2, "should reuse cached token, no new payment on second cycle");
});

// ---------------------------------------------------------------------------
// 11. Guards: sats cap refused
// ---------------------------------------------------------------------------

test("guard: over maxAutoPaySats → PaymentRejected", async () => {
  const mac = buildMacaroonB64("cap-guard-id");
  const engine = new L402Engine(stubPayer(), { maxAutoPaySats: 100 });

  await assert.rejects(
    () => engine.handleChallenge("https://api.example.com/r", makeChallenge(mac, VALID_INVOICE), 500),
    PaymentRejected,
  );
});

test("guard: over cap but approver returns true → payment proceeds", async () => {
  const mac = buildMacaroonB64("cap-approve-id");
  const engine = new L402Engine(stubPayer("approved_preimage"), {
    maxAutoPaySats: 100,
    approve: () => true,
  });

  const header = await engine.handleChallenge(
    "https://api.example.com/r",
    makeChallenge(mac, VALID_INVOICE),
    500,
  );
  assert.ok(header.startsWith("L402 "), "should build auth header when approved");
});

test("guard: over cap but approver returns false → PaymentRejected", async () => {
  const mac = buildMacaroonB64("cap-deny-id");
  const engine = new L402Engine(stubPayer(), {
    maxAutoPaySats: 100,
    approve: () => false,
  });

  await assert.rejects(
    () => engine.handleChallenge("https://api.example.com/r", makeChallenge(mac, VALID_INVOICE), 500),
    PaymentRejected,
  );
});

// ---------------------------------------------------------------------------
// 12. Guards: denied domain
// ---------------------------------------------------------------------------

test("guard: denied domain → PaymentRejected", async () => {
  const mac = buildMacaroonB64("deny-dom-id");
  const engine = new L402Engine(stubPayer(), {
    deniedDomains: ["evil.example.com"],
  });

  await assert.rejects(
    () =>
      engine.handleChallenge(
        "https://evil.example.com/resource",
        makeChallenge(mac, VALID_INVOICE),
        1,
      ),
    PaymentRejected,
  );
});

test("guard: subdomain of denied domain → PaymentRejected", async () => {
  const mac = buildMacaroonB64("deny-sub-id");
  const engine = new L402Engine(stubPayer(), {
    deniedDomains: ["evil.com"],
  });

  await assert.rejects(
    () =>
      engine.handleChallenge(
        "https://sub.evil.com/resource",
        makeChallenge(mac, VALID_INVOICE),
        1,
      ),
    PaymentRejected,
  );
});

test("guard: domain not in allowedDomains → PaymentRejected", async () => {
  const mac = buildMacaroonB64("allow-dom-id");
  const engine = new L402Engine(stubPayer(), {
    allowedDomains: ["trusted.example.com"],
  });

  await assert.rejects(
    () =>
      engine.handleChallenge(
        "https://untrusted.example.com/resource",
        makeChallenge(mac, VALID_INVOICE),
        1,
      ),
    PaymentRejected,
  );
});

test("guard: domain in allowedDomains → payment proceeds", async () => {
  const mac = buildMacaroonB64("allow-ok-id");
  const engine = new L402Engine(stubPayer("allowed_preimage"), {
    allowedDomains: ["trusted.example.com"],
  });

  const header = await engine.handleChallenge(
    "https://trusted.example.com/resource",
    makeChallenge(mac, VALID_INVOICE),
    1,
  );
  assert.ok(header.includes("allowed_preimage"));
});

// ---------------------------------------------------------------------------
// 13. Null / faulted preimage → PreimageError
// ---------------------------------------------------------------------------

test("null preimage → PreimageError", async () => {
  const mac = buildMacaroonB64("null-preimage-id");
  const engine = new L402Engine(nullPayer());

  await assert.rejects(
    () => engine.handleChallenge("https://api.example.com/r", makeChallenge(mac, VALID_INVOICE), 1),
    PreimageError,
  );
});

test("faulted preimage (preimageError set) → PreimageError", async () => {
  const mac = buildMacaroonB64("faulted-preimage-id");
  const engine = new L402Engine(faultedPayer("payment routing failed"));

  await assert.rejects(
    () => engine.handleChallenge("https://api.example.com/r", makeChallenge(mac, VALID_INVOICE), 1),
    PreimageError,
  );
});

// ---------------------------------------------------------------------------
// 14. Audit sink receives events
// ---------------------------------------------------------------------------

test("audit: events emitted in correct sequence for happy-path pay", async () => {
  const mac = buildMacaroonB64("audit-id");
  const events = [];
  const engine = new L402Engine(stubPayer("audit_preimage"), {
    audit: (e) => events.push(e.event),
  });

  await engine.handleChallenge(
    "https://api.example.com/r",
    makeChallenge(mac, VALID_INVOICE),
    1,
  );

  assert.ok(events.includes("challenge_parsed"), "should emit challenge_parsed");
  assert.ok(events.includes("paying"), "should emit paying");
  assert.ok(events.includes("paid"), "should emit paid");
});

test("audit: cache_hit emitted on second call", async () => {
  const mac = buildMacaroonB64("audit-cache-id", ["services=mysvc"]);
  const events = [];
  const engine = new L402Engine(stubPayer("cp"), {
    audit: (e) => events.push(e.event),
  });
  const header = makeChallenge(mac, VALID_INVOICE);
  await engine.handleChallenge("https://api.example.com/r", header, 1);
  await engine.handleChallenge("https://api.example.com/r", header, 1);

  const cacheHits = events.filter((e) => e === "cache_hit");
  assert.equal(cacheHits.length, 1, "should emit one cache_hit on second call");
});

// ---------------------------------------------------------------------------
// 15. fetchPaid: non-402 response passes through unchanged
// ---------------------------------------------------------------------------

test("fetchPaid: 200 response passes through without payment", async () => {
  let payCount = 0;
  const payer = (_inv, _sats) => {
    payCount++;
    return { preimage: "never", preimageError: null };
  };
  const engine = new L402Engine(payer);

  const fetcher = makeFetcher([
    { status: 200, headers: { "content-type": "text/plain" }, body: "hello" },
  ]);

  const result = await engine.fetchPaid("https://api.example.com/free", fetcher);
  assert.equal(result.status, 200);
  assert.equal(result.body, "hello");
  assert.equal(result.paidSats, 0);
  assert.equal(result.cached, false);
  assert.equal(payCount, 0, "should not pay for non-402");
});

// ---------------------------------------------------------------------------
// 16. fetchPaid: 402 with no WWW-Authenticate → InvalidChallenge
// ---------------------------------------------------------------------------

test("fetchPaid: 402 with no WWW-Authenticate → InvalidChallenge", async () => {
  const engine = new L402Engine(stubPayer());

  const fetcher = makeFetcher([
    { status: 402, headers: {}, body: "" },
  ]);

  await assert.rejects(
    () => engine.fetchPaid("https://api.example.com/r", fetcher),
    InvalidChallenge,
  );
});

// ---------------------------------------------------------------------------
// 17. MemoryTokenStore: explicit get/set/delete/clear
// ---------------------------------------------------------------------------

test("MemoryTokenStore: basic operations", () => {
  const store = new MemoryTokenStore();
  const token = {
    authHeader: "L402 m:p",
    macaroonB64: "m",
    preimage: "p",
    scopeKey: "svc:test",
    scope: {},
    paidSats: 1,
    acquiredAt: Date.now(),
  };

  assert.equal(store.get("svc:test"), undefined);
  store.set(token);
  assert.deepEqual(store.get("svc:test"), token);
  store.delete("svc:test");
  assert.equal(store.get("svc:test"), undefined);

  store.set(token);
  store.clear();
  assert.equal(store.get("svc:test"), undefined);
});

// ---------------------------------------------------------------------------
// 18. fetchPaid: cached token used when scope matches (was_cached path)
// ---------------------------------------------------------------------------

test("fetchPaid: cached token replayed — no payment, cached=true", async () => {
  const mac = buildMacaroonB64("fetch-cache-id", ["services=cachesvc"]);
  const inv = "lnbc100n1fetch_cache_inv";
  let payCount = 0;
  const payer = (_inv, _sats) => {
    payCount++;
    return { preimage: "cached_p", preimageError: null };
  };
  const engine = new L402Engine(payer);
  const url = "https://api.example.com/r";

  // Prime the cache with a first fetchPaid call
  const fetcher1 = makeFetcher([
    { status: 402, headers: { "WWW-Authenticate": makeChallenge(mac, inv) }, body: "" },
    { status: 200, headers: {}, body: "first" },
  ]);
  await engine.fetchPaid(url, fetcher1, { sats: 1 });
  assert.equal(payCount, 1);

  // Second call: server returns 402 with same scope → engine uses cache → 200
  const fetcher2 = makeFetcher([
    { status: 402, headers: { "WWW-Authenticate": makeChallenge(mac, inv) }, body: "" },
    { status: 200, headers: {}, body: "second" },
  ]);
  const result2 = await engine.fetchPaid(url, fetcher2, { sats: 1 });
  assert.equal(result2.status, 200);
  assert.equal(result2.cached, true, "should be marked as cached");
  assert.equal(result2.paidSats, 0, "should report 0 sats paid on cache hit");
  assert.equal(payCount, 1, "should not have paid again");
});

// ---------------------------------------------------------------------------
// 19. agentPayer: wraps an agent-like object correctly
// ---------------------------------------------------------------------------

test("agentPayer: wraps agent.pay and returns PaidResult", async () => {
  const fakeAgent = {
    async pay(_opts) {
      return { preimage: "agent_preimage", preimageError: null };
    },
  };
  const payer = agentPayer(fakeAgent);
  const result = await payer("lnbctest", 42);
  assert.equal(result.preimage, "agent_preimage");
  assert.equal(result.preimageError, null);
});

test("agentPayer: propagates null preimage", async () => {
  const fakeAgent = {
    async pay(_opts) {
      return { preimage: null, preimageError: "routing failed" };
    },
  };
  const payer = agentPayer(fakeAgent);
  const result = await payer("lnbctest", 1);
  assert.equal(result.preimage, null);
  assert.equal(result.preimageError, "routing failed");
});

// ---------------------------------------------------------------------------
// 20. count≤0 caveat → treated as quota exhausted → cache miss
// ---------------------------------------------------------------------------

test("cache: count=0 caveat treats token as exhausted", async () => {
  const mac = buildMacaroonB64("count-zero-id", ["count=0"]);
  let payCount = 0;
  const payer = (_inv, _sats) => {
    payCount++;
    return { preimage: `count_p${payCount}`, preimageError: null };
  };
  const engine = new L402Engine(payer);
  const url = "https://api.example.com/r";
  const header = makeChallenge(mac, VALID_INVOICE);

  await engine.handleChallenge(url, header, 1);
  assert.equal(payCount, 1);

  // Second call: count=0 caveat means cache miss → re-pay
  await engine.handleChallenge(url, header, 1);
  assert.equal(payCount, 2, "count=0 should trigger re-pay");
});
