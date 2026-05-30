// Webhook verification tests — run against the built dist/ output.
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";

import {
  parseWebhook,
  verifyWebhook,
  WebhookVerificationError,
} from "../dist/index.js";

const SECRET = "whsec_test_secret";
const PAYLOAD =
  '{"data":{"transaction_id":"tx_1"},"event":"payment.settled","ts":1748140800}';

function goodSig(payload, secret) {
  const mac = createHmac("sha256", secret).update(payload).digest("hex");
  return `sha256=${mac}`;
}

test("verifyWebhook accepts a valid signature", () => {
  assert.equal(verifyWebhook(PAYLOAD, goodSig(PAYLOAD, SECRET), SECRET), true);
});

test("verifyWebhook accepts a Uint8Array payload", () => {
  const bytes = new TextEncoder().encode(PAYLOAD);
  assert.equal(verifyWebhook(bytes, goodSig(PAYLOAD, SECRET), SECRET), true);
});

test("verifyWebhook rejects a tampered payload", () => {
  const sig = goodSig(PAYLOAD, SECRET);
  assert.equal(verifyWebhook(PAYLOAD + " ", sig, SECRET), false);
});

test("verifyWebhook rejects the wrong secret", () => {
  const sig = goodSig(PAYLOAD, SECRET);
  assert.equal(verifyWebhook(PAYLOAD, sig, "wrong-secret"), false);
});

test("verifyWebhook rejects an empty signature", () => {
  assert.equal(verifyWebhook(PAYLOAD, "", SECRET), false);
});

test("parseWebhook returns the decoded event", () => {
  const sig = goodSig(PAYLOAD, SECRET);
  const event = parseWebhook(PAYLOAD, sig, SECRET);
  assert.equal(event.event, "payment.settled");
  assert.equal(event.data.transaction_id, "tx_1");
});

test("parseWebhook throws on an invalid signature", () => {
  assert.throws(
    () => parseWebhook(PAYLOAD, "sha256=deadbeef", SECRET),
    WebhookVerificationError,
  );
});
