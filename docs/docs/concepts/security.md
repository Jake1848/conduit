# Security model

What Conduit defends against, and what it doesn't.

## Self-hosted by construction

Conduit is software **you** run, not a service that holds your money. Be precise
about who custodies what — the operator level and the agent level are different.

**At the operator level, you are self-hosted:**

- **You control the node.** Conduit talks to LND only through the macaroon you
  mount into it. The seed and the channels are yours; Conduit never holds funds
  and cannot move them without the node you own.
- **You control the keys.** The bootstrap API key is **your** master key to
  **your own** Conduit instance — it mints the scoped keys you hand to agents.
  Guard it like the LND macaroon.
- **No Conduit SaaS in the path.** There is no Conduit-operated wallet and
  nothing that phones home. No outside middleman can freeze, seize, or
  rehypothecate your sats. Turn Conduit off and the money is still in your
  channels.

**At the agent level, Conduit is custodial by construction:**

- Agent balances are **virtual IOUs** in Conduit's ledger — not on-chain or
  channel balances of their own. As operator **you** credit, debit, and can
  sweep them. The underlying sats stay in your channels under your keys.
- An agent holds a **scoped API key, not a signing key.** It can request
  payments within its policy; it can never touch a Bitcoin private key. The
  operator is the custodian for every agent.

Conduit's job is to be the **policy + accounting layer** in front of a node you
own. The rest of this page is about what that layer does and does not protect.

## In scope

- **An LLM agent goes off the rails** and tries to drain its wallet. The
  policy engine caps every payment before it reaches LND. Fail-closed.
- **A stolen API key**. Keys are scoped (`read`/`write`/`admin`). A `read`
  key cannot move funds. Keys are stored as bcrypt hashes — the operator
  sees the raw value exactly once at creation.
- **A vendor going hostile**. Add their address to `blocklist`; further
  payments to them are immediately denied.
- **Webhook delivery to a hostile endpoint**. Every webhook body is
  HMAC-signed with a per-subscription secret. Verify
  `X-Conduit-Signature` before trusting payloads.

## The payment reconciler

A Lightning send has a window where Conduit has told LND to pay but hasn't
yet heard back. If the call to LND times out or errors in that window,
Conduit genuinely **does not know** whether the payment settled. Refunding
blindly would risk a double-spend (the payment may still land on the
network); not refunding would strand the agent's sats. Conduit resolves this
deterministically rather than guessing.

On an unknown-state result the payment route:

- leaves the transaction `pending` with a `needs_reconciliation` marker,
- does **not** refund — the payment may yet settle,
- records the `payment_hash` so the payment can be looked up later.

A background **reconciler** then closes the loop. It sweeps every **60
seconds** for pending outbound payments older than **90 seconds** (safely
past LND's own 60s payment timeout) and asks LND for the real outcome via
`lookuppayment`:

- **SUCCEEDED** → mark settled, refund any unused fee budget, fire
  `payment.settled` (with `reconciled: true`).
- **FAILED** → mark failed, refund the full debit (sats + fee budget), fire
  `payment.failed` (with `reconciled: true`).
- **IN_FLIGHT / UNKNOWN** → leave it; the next sweep checks again.

The guarantee: an agent's money is **never permanently lost** to an
ambiguous network failure — every payment ends up either settled (and the
agent got what it paid for) or refunded. The only rows needing manual
attention are legacy ones with no `payment_hash`, which are logged for the
operator.

## Out of scope

- **VPS compromise**. If an attacker has root on the LND host, they have
  the macaroon. Conduit cannot defend against that — use a hardware-backed
  signing flow (LND watchtowers + remote signer) if your value-at-rest
  justifies it.
- **Lightning Network routing failures**. A `payment_failed` is reported
  as such; Conduit doesn't promise universal reachability.
- **Bitcoin volatility**. Sats are sats.

## What you MUST do

- Store the LND seed phrase **on paper**, off the VPS. Never in cloud
  storage, never in git.
- Run `infra/scripts/backup_channels.sh` on a cron to replicate the SCB
  off-box.
- Restrict the macaroon file: `chmod 600`, owned by `conduit`.
- Keep LND's gRPC (`10009`) and REST (`8080`) ports behind the firewall.
  Only `:443` (the Core API) should be public.
- Use `ck_test_…` keys with `LND_MOCK=true` in CI; never put production
  keys in CI environment variables.

See [`infra/README.md`](https://github.com/Jake1848/conduit/blob/main/infra/README.md)
for the full operations checklist.
