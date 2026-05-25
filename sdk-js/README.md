# @conduit/sdk

TypeScript SDK for **Conduit** — Bitcoin Lightning payment infrastructure for
autonomous AI agents.

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

Reads `CONDUIT_API_KEY` and `CONDUIT_API_URL` from the environment by default.

```ts
import { Conduit, setDefaultClient } from '@conduit/sdk';
setDefaultClient(new Conduit({ apiKey: 'ck_live_...', baseUrl: 'https://api.conduit.energy' }));
```

## Requirements

- Node.js 20+ (uses the built-in `fetch`).
- Works in the browser if you bring your own `fetch`-compatible implementation.
