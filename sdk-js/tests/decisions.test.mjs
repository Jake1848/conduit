// Decision-record tests — run against the built dist/ output.
import assert from "node:assert/strict";
import { test } from "node:test";

import { ConduitClient } from "../dist/index.js";

function jsonResponse(status, body, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

// A fake fetch that records calls and dispatches to responder(callIndex, url, init).
function makeFetch(responder) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init });
    return responder(calls.length, url, init);
  };
  fn.calls = calls;
  return fn;
}

function makeClient(fetchImpl) {
  return new ConduitClient({
    apiKey: "ck_test_x",
    baseUrl: "http://mock",
    fetchImpl,
    retryBackoffBaseMs: 0,
  });
}

// A rejected decision whose per_transaction limit was blown — the margin headline.
const DECISION = {
  id: "dec_1",
  agent_id: "agt_1",
  outcome: "rejected",
  reason_code: "POLICY_VIOLATION",
  requested_sats: 5000,
  destination: "02" + "aa".repeat(32),
  destination_kind: "keysend",
  allowlist_status: "allowed",
  api_key_id: "key_1",
  caller_tag: "tool:search",
  balance_at_decision_sats: 12000,
  thresholds: [
    {
      rule: "per_transaction",
      unit: "sats",
      limit: 1000,
      attempted: 5000,
      current: 0,
      margin_abs: -4000,
      margin_pct: -400,
      violated: true,
    },
  ],
  binding_rule: "per_transaction",
  min_margin_pct: -400,
  policy_snapshot: { max_per_transaction: 1000 },
  policy_hash: "ab".repeat(16),
  tx_id: null,
  created_at: "2026-06-27T00:00:00+00:00",
};

test("listDecisions({ agentId }) hits the agent path and maps the margin fields", async () => {
  const f = makeFetch(() => jsonResponse(200, { data: [DECISION], has_more: false }));
  const decisions = await makeClient(f).listDecisions({
    agentId: "agt_1",
    outcome: "rejected",
    limit: 10,
  });

  assert.equal(f.calls.length, 1);
  const url = f.calls[0].url;
  assert.ok(url.includes("/v1/agents/agt_1/decisions"), url);
  assert.ok(url.includes("limit=10"), url);
  assert.ok(url.includes("outcome=rejected"), url);
  assert.equal(f.calls[0].init.method, "GET");

  assert.equal(decisions.length, 1);
  const d = decisions[0];
  assert.equal(d.id, "dec_1");
  assert.equal(d.agentId, "agt_1");
  assert.equal(d.outcome, "rejected");
  assert.equal(d.requestedSats, 5000);
  assert.equal(d.destinationKind, "keysend");
  assert.equal(d.apiKeyId, "key_1");
  assert.equal(d.callerTag, "tool:search");
  assert.equal(d.bindingRule, "per_transaction");
  assert.equal(d.minMarginPct, -400);
  assert.deepEqual(d.policySnapshot, { max_per_transaction: 1000 });
  assert.equal(d.txId, null);
  assert.ok(d.createdAt instanceof Date);

  // The margin is the headline — snake_case wire → camelCase domain.
  const t = d.thresholds[0];
  assert.equal(t.rule, "per_transaction");
  assert.equal(t.marginAbs, -4000);
  assert.equal(t.marginPct, -400);
  assert.equal(t.violated, true);
});

test("listDecisions() without an agentId uses the fleet-wide recent feed", async () => {
  const f = makeFetch(() => jsonResponse(200, { data: [DECISION], has_more: false }));
  const decisions = await makeClient(f).listDecisions({ outcome: "settled" });

  const url = f.calls[0].url;
  assert.ok(url.includes("/v1/decisions/recent"), url);
  assert.ok(!url.includes("/v1/agents/"), url);
  assert.ok(url.includes("outcome=settled"), url);
  assert.ok(url.includes("limit=50"), url); // default limit
  assert.equal(decisions.length, 1);
  assert.equal(decisions[0].id, "dec_1");
});

test("getDecision(id) fetches a single decision by id", async () => {
  const f = makeFetch(() => jsonResponse(200, DECISION));
  const d = await makeClient(f).getDecision("dec_1");

  assert.equal(f.calls.length, 1);
  assert.ok(f.calls[0].url.includes("/v1/decisions/dec_1"), f.calls[0].url);
  assert.equal(f.calls[0].init.method, "GET");
  assert.equal(d.id, "dec_1");
  assert.equal(d.balanceAtDecisionSats, 12000);
  assert.equal(d.thresholds[0].marginAbs, -4000);
  assert.ok(d.createdAt instanceof Date);
});
