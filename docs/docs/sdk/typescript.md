# TypeScript SDK

```bash
npm i @conduit/sdk
```

```ts
import { Agent } from '@conduit/sdk';

const agent = await Agent.create({
  name: 'compute-router-7',
  dailyLimit: 50_000,
});

await agent.policy.attach({
  maxPerHour: 10_000,
  allowlist: ['02beef...'],
});

const receipt = await agent.pay({
  to: 'compute-node-7@lnd.conduit.energy',
  sats: 150,
  memo: 'dataset query',
});

console.log(receipt.hash, receipt.settledInMs);
```

## Configuration

Reads `CONDUIT_API_KEY` and `CONDUIT_API_URL` from the environment by
default. To configure explicitly:

```ts
import { Conduit, setDefaultClient } from '@conduit/sdk';

setDefaultClient(
  new Conduit({
    apiKey: 'ck_live_…',
    baseUrl: 'https://api.conduit.energy',
  }),
);
```

## Methods (mirror the Python SDK)

| Python                                | TypeScript |
| ------------------------------------- | ---------- |
| `Agent.create(name=, daily_limit=)`   | `Agent.create({ name, dailyLimit })` |
| `agent.policy.attach(max_per_hour=)`  | `agent.policy.attach({ maxPerHour })` |
| `agent.pay(to=, sats=, memo=)`        | `agent.pay({ to, sats, memo })` |
| `agent.keysend(pubkey, sats)`         | `agent.keysend(pubkey, sats)` |
| `agent.receive(amount, memo=)`        | `agent.receive(amount, { memo })` |
| `agent.balance` (property)            | `await agent.balance()` |
| `agent.transactions(limit=50)`        | `await agent.transactions(50)` |

## Retries

Same behavior as the Python SDK:

- Retries on **HTTP 429**, **5xx**, and **network/timeout** errors.
- **Exponential backoff** — 1s, 2s, 4s.
- Honors `Retry-After` (capped at 60s); empty / non-numeric / negative values
  fall back to exponential backoff.
- **Never** retries other 4xx.
- Up to `maxRetries` retries (default **3** → 4 total attempts).

```ts
import { Conduit, setDefaultClient } from '@conduit/sdk';

setDefaultClient(new Conduit({ maxRetries: 5 })); // or 0 to disable
```

## Idempotency

Every payment method (`pay`, `sendInvoice`, `keysend`) sends an
`Idempotency-Key` header automatically — a fresh UUID4 per call, **reused
across the SDK's own retries**. Pass an explicit key to make a *manual*
retry idempotent:

```ts
const key = 'order-12345';
await agent.pay({ to: 'alice@strike.me', sats: 500, idempotencyKey: key });
// keysend / sendInvoice take it in their options bag:
await agent.keysend('03abc...', 500, undefined, { idempotencyKey: key });
```

Reusing a key with a **different** body throws a `ConduitError`
(`code === "IDEMPOTENCY_CONFLICT"`). Full semantics in the
[Payments API → Idempotency](../api/payments.md#idempotency).

## Webhook verification

```ts
import express from 'express';
import { parseWebhook, WebhookVerificationError } from '@conduit/sdk';

const app = express();
const WEBHOOK_SECRET = 'whsec_...'; // secret returned when you created the webhook

// IMPORTANT: capture the RAW body — do not let JSON middleware re-serialize it.
app.post(
  '/conduit/events',
  express.raw({ type: 'application/json' }),
  (req, res) => {
    const signature = req.header('X-Conduit-Signature') ?? '';
    try {
      const event = parseWebhook(req.body, signature, WEBHOOK_SECRET);
      // event == { event: "payment.settled", data: {...}, ts: 1748140800 }
      res.json({ ok: true });
    } catch (e) {
      if (e instanceof WebhookVerificationError) {
        res.status(400).send('bad signature');
      } else {
        throw e;
      }
    }
  },
);
```

`verifyWebhook(payload, signature, secret)` returns a boolean if you'd rather
branch yourself. Both accept a `string` or `Uint8Array` payload and use
Node's `crypto.timingSafeEqual` for a constant-time comparison.

> Always verify the **raw request bytes**. `express.raw()` gives you a
> `Buffer`; `express.json()` would re-serialize and break the signature.

## Errors

```ts
import { PolicyViolation } from '@conduit/sdk';

try {
  await agent.pay({ to, sats });
} catch (e) {
  if (e instanceof PolicyViolation) {
    console.log(e.code, e.message);
  } else {
    throw e;
  }
}
```

## Runtime

Requires Node.js ≥ 20 (uses the built-in `fetch`). In the browser, pass a
custom `fetchImpl` to `new Conduit({ fetchImpl })`. Webhook verification
(`verifyWebhook` / `parseWebhook`) uses `node:crypto` and is intended for
server-side receivers.
