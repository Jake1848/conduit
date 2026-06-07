# Security Policy

Conduit is self-hosted, open-source Bitcoin / Lightning payment infrastructure. It
runs on your own machines, against your own LND node — there is no Conduit SaaS and
Conduit never holds your funds or phones home. Because real money can move through a
production deployment, we take security reports seriously and ask that you disclose
them responsibly.

> Conduit is currently **v0.8.1 — testnet-ready, mainnet in progress**. It has run
> live on testnet and regtest only. There has been no external security audit. Treat
> the software accordingly.

## Supported Versions

Security fixes are provided for the current `0.8.x` release line.

| Version | Supported          |
| ------- | ------------------ |
| 0.8.x   | :white_check_mark: |
| < 0.8   | :x:                |

Older versions are not maintained — please upgrade to the latest `0.8.x` release
before reporting an issue.

## Scope

**In scope**

- The Conduit core API (`core/`) — auth, the virtual per-agent ledger, payment
  phases, reconciliation, admin endpoints.
- The official SDKs (`sdk-python/`, `sdk-js/`).

**Out of scope**

- Your own self-hosted deployment: server hardening, OS/network configuration, your
  LND node, your macaroons, TLS material, wallet seeds, and any keys or secrets you
  manage. Conduit is custodial *by construction* at the agent layer — agents hold API
  keys, the operator (you) controls the underlying LND node and funds — so protecting
  the host and its key material is the operator's responsibility.
- The hosted demo / testnet environment (e.g. `api.conduit.energy`). Please do **not**
  run automated scans, fuzzing, or live exploitation against the public testnet
  deployment; reproduce findings locally on regtest/testnet instead.
- Vulnerabilities in third-party dependencies that have no exploitable path through
  Conduit (report those upstream).

## Reporting a Vulnerability

**Please report privately. Do not open a public GitHub issue, pull request, or
discussion for a suspected vulnerability**, and do not test against the live testnet
deployment.

Two private channels are available:

1. **GitHub Security Advisories (preferred).** Use the repository's
   **Security → Report a vulnerability** flow ("Report a vulnerability" / private
   vulnerability reporting). This keeps the report private and lets us collaborate on a
   fix and coordinated disclosure in one place.
2. **Email.** `security@conduit.energy`

   > Maintainer note: confirm that `security@conduit.energy` is a monitored inbox (or
   > replace it with one) before publishing. A security contact that no one reads is
   > worse than none.

Please include, where possible:

- A description of the issue and its impact.
- The affected component and version / commit.
- Step-by-step reproduction (a minimal regtest/testnet proof-of-concept is ideal).
- Any logs, stack traces, or configuration needed to reproduce.

## Disclosure Process

- We aim to acknowledge a report within **3 business days**.
- We will work with you on a fix and a coordinated disclosure date.
- Our target disclosure window is **90 days** from the initial report, or sooner once a
  fix is released. We will keep you updated if more time is genuinely needed.
- With your permission, we are happy to credit you in the advisory and release notes.

Thank you for helping keep Conduit and its operators safe.
