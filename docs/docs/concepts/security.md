# Security model

What Conduit defends against, and what it doesn't.

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
