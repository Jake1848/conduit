# Treasury — operator guide

The **Treasury** page (admin-only) is where you, the operator, see the revenue
your Conduit instance has accrued and move that accrued BTC out of your node
on-chain — safely, behind a solvency guard.

## 1. Log in

The console talks directly to your Conduit API with an **admin-scope** API key
(stored in your browser's localStorage — nothing is hardcoded, so the same
console drives any instance you point it at).

1. Open the console (e.g. `https://console.conduit.energy`, or your own deploy).
2. Enter:
   - **API URL** — your Conduit instance, e.g. `https://api.your-domain.com`
   - **API key** — an **admin** key (`ck_live_…` on mainnet, `ck_test_…` otherwise). Mint one on the **API Keys** page (admin scope).
3. The **Treasury** item only appears in the sidebar for an admin key. A non-admin key sees "Admin access required" — the page never exposes node liquidity to a read/write key.

## 2. View revenue and holdings

The four stat cards at the top:

- **Revenue (all-time)** — total platform fees collected, with a USD estimate.
- **Revenue today** — fees collected since 00:00 UTC.
- **Node assets** — your node's total liquidity (on-chain confirmed + local channel balance), in BTC + USD.
- **Solvency** — the at-a-glance health ratio (e.g. `7.4× healthy`).

The **Revenue** panel charts fees per day; toggle **7d / 30d** and read the total
+ average/day for the window. The **Liquidity & solvency** panel breaks holdings
down (on-chain, channels, total assets, what you owe agents, and what's
withdrawable right now), each with a USD estimate. The **Node** strip shows
chain-sync status, block height, and active channels.

## 3. Revenue vs. node liquidity (important)

**Revenue is an accounting figure, not a separate wallet.** It is the sum of the
per-transaction platform fees on settled payments. Those sats are *retained in
your own LND node, commingled with the rest of your liquidity* — there is no
segregated "fee balance" sitting somewhere.

So "you've earned 1,300,000 sats in fees" does **not** mean there's a 1,300,000-sat
pot to sweep. It means your node holds that much *more* than it otherwise would.
What you can actually move on-chain is bounded by **node liquidity** and the
**solvency guard**, not by the revenue figure.

## 4. Check solvency before withdrawing

Conduit runs a virtual per-agent ledger over your single node. Your **liabilities**
are the sum of all agent balances (what you owe your agents); your **assets** are
your node's on-chain + channel liquidity. **Solvency ratio = assets ÷ liabilities.**

- `≥ 2×` — healthy
- `1.25×–2×` — caution
- `< 1.25×` — tight
- `< 1×` — insolvent (you owe agents more than the node holds)

Glance at the **Solvency** card before moving funds. The page reports it
conservatively if the node can't be read.

## 5. Withdraw accrued BTC safely

In **Withdraw accrued BTC**:

1. Enter an **amount** (or hit **Max** for the full withdrawable headroom). The
   max already accounts for solvency + a small on-chain fee reserve.
2. Enter a **destination address** (mainnet `bc1…`, testnet `tb1…`, regtest `bcrt1…`).
3. Optionally set a **fee rate** (sat/vB); otherwise LND estimates.
4. Click **Review withdrawal**. A confirmation dialog re-reads live liquidity and
   shows the amount (+USD), the destination, and your **solvency after** the send.
5. Confirm. **On a mainnet instance** the dialog flags "MAINNET — real funds" and
   makes you **type the exact amount** to arm the button (a fat-finger guard).

Withdrawals are **idempotent**: if the response is lost and you retry, the same
request dedupes to the same transaction — it will not double-broadcast.

Completed transfers appear in the **Bitcoin transfers** table (your on-chain
audit trail): date, amount, address, txid (linked to mempool.space on
testnet/mainnet), and status (`broadcast` / `failed`).

## 6. The solvency guard (why a withdrawal can be refused)

Every withdrawal is gated server-side: **after the send, node assets must still
cover Σ agent balances** (minus a small fee reserve). If a requested amount would
drop you below what you owe agents, the API refuses it with a clear error and the
"withdrawable now" figure. This is deliberate — it stops you from accidentally
spending funds that are backing your agents' balances. You can only ever withdraw
the *headroom* above your liabilities, never into them.
