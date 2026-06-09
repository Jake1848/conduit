# @conduit-btc/sdk

TypeScript SDK for **Conduit** — self-hosted, non-custodial Bitcoin Lightning
payment infrastructure for autonomous AI agents.

**Your node, your keys, your rules.** Conduit is software tooling that you run
on your own infrastructure, against your own LND node, with your own keys. It
never touches your funds — this SDK is a thin client for *your* Conduit instance.

```bash
npm install @conduit-btc/sdk
```

## Quickstart

Point the SDK at the Conduit instance you deployed (a 5-minute Docker deploy
against your own LND node), create an agent, and send a payment:

```ts
import { Agent, Conduit, setDefaultClient } from '@conduit-btc/sdk';

// Connect to YOUR self-hosted Conduit instance
setDefaultClient(
  new Conduit({
    apiKey: 'ck_live_...',                 // an API key from your instance
    baseUrl: 'https://conduit.example.com', // your Conduit URL
  }),
);

// Create an autonomous wallet with an optional spending policy
const agent = await Agent.create({
  name: 'compute-router-7',
  dailyLimit: 50_000,
});

await agent.policy.attach({
  maxPerHour: 10_000,
  allowlist: ['02beef...'],
});

// Send a Lightning payment
const receipt = await agent.pay({
  to: 'compute-node-7@lnd.example.com',
  sats: 150,
  memo: 'dataset query',
});

console.log(receipt.hash, receipt.settledInMs);
console.log(receipt.feeSats, receipt.platformFeeSats);
```

## Client-centric API (`ConduitClient`)

Prefer a single client object with explicit methods over the `Agent`
active-record style? `ConduitClient` wraps the same retrying, idempotent HTTP
client and adds operator funding (`creditAgent`):

```ts
import { ConduitClient } from '@conduit-btc/sdk';

const client = new ConduitClient({
  baseUrl: 'https://conduit.example.com',
  apiKey: 'ck_live_...',
});

const agent = await client.createAgent({ name: 'compute-router-7' });
await client.creditAgent(agent.id, { sats: 10_000 });    // operator funds the agent

const receipt = await client.sendPayment(agent.id, { destPubkey: '02beef...', sats: 500 });
console.log(receipt.status, receipt.platformFeeSats);     // 'settled', 2

console.log((await client.getBalance(agent.id)).available);
for (const tx of await client.listTransactions(agent.id)) {
  console.log(tx.direction, tx.amountSats, tx.status);
}
```

Both styles talk to the same instance — use whichever you prefer.

## Platform fee on receipts

Every payment receipt includes a **`platformFeeSats`** field (`platform_fee_sats`
on the wire) — the per-transaction platform fee in satoshis configured by the
operator who deployed the instance. It is **separate** from `feeSats` (the LND
routing fee):

- `feeSats` — the Lightning Network routing fee paid to route the payment.
- `platformFeeSats` — the operator's usage-based revenue, charged on top, kept
  on settle, and refunded in full if the payment fails.

The fee is configured on your instance via `PLATFORM_FEE_PERCENT` (default `0.5`%),
`PLATFORM_FEE_MIN_SATS` (default `1`), and `PLATFORM_FEE_MAX_SATS` (default `1000`).

```ts
const receipt = await agent.pay({ to: '...', sats: 10_000 });
console.log(receipt.amountSats);     // 10000
console.log(receipt.feeSats);        // LND routing fee
console.log(receipt.platformFeeSats); // your platform's per-tx revenue
```

## Configuration

Reads `CONDUIT_API_KEY` and `CONDUIT_API_URL` from the environment by default.
Set `CONDUIT_API_URL` to the URL of your own Conduit deployment (the default,
`https://api.conduit.energy`, is the hosted demo console).

```ts
import { Conduit, setDefaultClient } from '@conduit-btc/sdk';

setDefaultClient(
  new Conduit({ apiKey: 'ck_live_...', baseUrl: 'https://conduit.example.com' }),
);
```

## Requirements

- Node.js 20+ (uses the built-in `fetch`).
- Works in the browser if you bring your own `fetch`-compatible implementation.

## Links

- Repository: <https://github.com/Jake1848/conduit>
- License: MIT
