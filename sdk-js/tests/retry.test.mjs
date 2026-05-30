// Retry + idempotency tests — run against the built dist/ output.
import assert from "node:assert/strict";
import { test } from "node:test";

import { backoffDelayMs } from "../dist/client.js";
import { Agent, Conduit, RateLimited } from "../dist/index.js";

function jsonResponse(status, body, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

const RECEIPT = {
  id: "tx_1",
  agent_id: "agt_1",
  status: "settled",
  hash: "ab".repeat(32),
  amount_sats: 100,
  fee_sats: 1,
  settled_in_ms: 5,
  destination: "02" + "aa".repeat(32),
  memo: null,
  created_at: "2026-05-27T00:00:00+00:00",
};

// A fake fetch that records calls and dispatches to responder(callIndex, init).
function makeFetch(responder) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init });
    return responder(calls.length, init);
  };
  fn.calls = calls;
  return fn;
}

function makeClient(fetchImpl, opts = {}) {
  return new Conduit({
    apiKey: "ck_test_x",
    baseUrl: "http://mock",
    fetchImpl,
    retryBackoffBaseMs: 0,
    ...opts,
  });
}

test("retries on 429 then succeeds, reusing the same idempotency key", async () => {
  const f = makeFetch((n) =>
    n === 1
      ? jsonResponse(
          429,
          { detail: { code: "RATE_LIMITED", detail: "slow down" } },
          { "Retry-After": "0" },
        )
      : jsonResponse(201, RECEIPT),
  );
  const c = makeClient(f);
  const data = await c.post("/v1/payments/send", { sats: 100 }, { idempotencyKey: "key-abc" });
  assert.equal(data.status, "settled");
  assert.equal(f.calls.length, 2);
  const keys = new Set(f.calls.map((x) => x.init.headers["Idempotency-Key"]));
  assert.deepEqual([...keys], ["key-abc"]);
});

test("retries on 503 then succeeds", async () => {
  const f = makeFetch((n) =>
    n <= 2 ? jsonResponse(503, { detail: { detail: "unavailable" } }) : jsonResponse(201, RECEIPT),
  );
  const c = makeClient(f);
  const data = await c.post("/v1/payments/send", { sats: 100 }, { idempotencyKey: "k" });
  assert.equal(data.status, "settled");
  assert.equal(f.calls.length, 3);
});

test("does not retry on a 4xx", async () => {
  const f = makeFetch(() =>
    jsonResponse(400, { detail: { code: "INVALID_INPUT", detail: "bad" } }),
  );
  const c = makeClient(f);
  await assert.rejects(() => c.post("/v1/payments/send", { sats: 0 }));
  assert.equal(f.calls.length, 1);
});

test("exhausts retries then raises", async () => {
  const f = makeFetch(() =>
    jsonResponse(429, { detail: { code: "RATE_LIMITED", detail: "no" } }),
  );
  const c = makeClient(f, { maxRetries: 3 });
  await assert.rejects(
    () => c.post("/v1/payments/send", { sats: 100 }, { idempotencyKey: "k" }),
    RateLimited,
  );
  assert.equal(f.calls.length, 4); // 1 initial + 3 retries
});

test("retries on a network error", async () => {
  const f = makeFetch((n) => {
    if (n === 1) throw new Error("connection refused");
    return jsonResponse(201, RECEIPT);
  });
  const c = makeClient(f);
  const data = await c.post("/v1/payments/send", { sats: 100 }, { idempotencyKey: "k" });
  assert.equal(data.status, "settled");
  assert.equal(f.calls.length, 2);
});

test("backoffDelayMs: exponential, Retry-After honored/capped, and safe fallbacks", () => {
  // Exponential schedule.
  assert.equal(backoffDelayMs(0, null, 1000, 60000), 1000);
  assert.equal(backoffDelayMs(1, null, 1000, 60000), 2000);
  assert.equal(backoffDelayMs(2, null, 1000, 60000), 4000);
  // Retry-After (seconds) honored and capped.
  assert.equal(backoffDelayMs(0, "2", 1000, 60000), 2000);
  assert.equal(backoffDelayMs(0, "9999", 1000, 60000), 60000);
  // Explicit 0 → retry immediately.
  assert.equal(backoffDelayMs(0, "0", 1000, 60000), 0);
  // Empty / whitespace / negative / non-numeric → fall back to exponential
  // (this is the bug the verifier caught: Number("") === 0).
  assert.equal(backoffDelayMs(0, "", 1000, 60000), 1000);
  assert.equal(backoffDelayMs(0, "   ", 1000, 60000), 1000);
  assert.equal(backoffDelayMs(1, "-5", 1000, 60000), 2000);
  assert.equal(backoffDelayMs(0, "abc", 1000, 60000), 1000);
});

test("Agent.keysend sends an Idempotency-Key and respects an explicit one", async () => {
  // Route both the agent-create and the payment through one fake fetch.
  const f = makeFetch((_n, init) => {
    const body = init.body ? JSON.parse(init.body) : {};
    if (body.name) {
      return jsonResponse(201, {
        id: "agt_1",
        name: body.name,
        pubkey: null,
        active: true,
        created_at: "2026-05-27T00:00:00+00:00",
      });
    }
    return jsonResponse(201, RECEIPT);
  });
  const client = makeClient(f);
  const agent = await Agent.create({ name: "a" }, client);

  await agent.keysend("02" + "aa".repeat(32), 100);
  const autoKey = f.calls.at(-1).init.headers["Idempotency-Key"];
  assert.ok(autoKey && autoKey.length > 0, "auto key present");

  await agent.keysend("02" + "bb".repeat(32), 100, undefined, { idempotencyKey: "fixed" });
  assert.equal(f.calls.at(-1).init.headers["Idempotency-Key"], "fixed");

  // Two auto-generated keys differ.
  await agent.keysend("02" + "cc".repeat(32), 100);
  const autoKey2 = f.calls.at(-1).init.headers["Idempotency-Key"];
  assert.notEqual(autoKey, autoKey2);
});
