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
custom `fetchImpl` to `new Conduit({ fetchImpl })`.
