import { createHmac, timingSafeEqual } from "node:crypto";

import { ConduitError } from "./errors.js";

/**
 * Verify and parse Conduit webhook deliveries.
 *
 * Every webhook Conduit sends carries an `X-Conduit-Signature` header of the
 * form `sha256=<hexdigest>` where the digest is HMAC-SHA256 over the RAW
 * request body bytes, keyed by the per-subscription secret you received when
 * you created the webhook. Always verify on the raw body, before any JSON
 * re-serialization.
 *
 *   import { parseWebhook } from "@conduit/sdk";
 *
 *   const event = parseWebhook(rawBody, req.headers["x-conduit-signature"], SECRET);
 *   // event == { event: "payment.settled", data: {...}, ts: ... }
 *
 * Uses Node's `crypto` — webhook receivers run server-side.
 */
export class WebhookVerificationError extends ConduitError {
  constructor(m: string, d: Record<string, unknown> = {}) {
    super(m, "WEBHOOK_VERIFICATION_ERROR", d);
    this.name = "WebhookVerificationError";
  }
}

/** Return true iff `signature` is a valid Conduit signature for `payload`. Constant-time. */
export function verifyWebhook(
  payload: string | Uint8Array,
  signature: string,
  secret: string,
): boolean {
  if (!signature || !secret) return false;
  const mac = createHmac("sha256", secret).update(payload).digest("hex");
  const expected = `sha256=${mac}`;
  const a = Buffer.from(expected, "utf8");
  const b = Buffer.from(signature, "utf8");
  // timingSafeEqual throws on length mismatch — guard first (length is not secret).
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

/**
 * Verify the signature, then return the decoded JSON body. Throws
 * `WebhookVerificationError` if the signature is invalid, so an unverified
 * payload can never reach your handler logic.
 */
export function parseWebhook<T = Record<string, unknown>>(
  payload: string | Uint8Array,
  signature: string,
  secret: string,
): T {
  if (!verifyWebhook(payload, signature, secret)) {
    throw new WebhookVerificationError(
      "Webhook signature verification failed — signature did not match the " +
        "payload under the provided secret.",
    );
  }
  const text =
    typeof payload === "string" ? payload : Buffer.from(payload).toString("utf8");
  return JSON.parse(text) as T;
}
