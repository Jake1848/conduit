# Conduit infrastructure

Conduit is **self-hosted and non-custodial**: you, the operator, run it on your
own box, in front of your own LND node, holding your own keys and channel funds.
Conduit never takes custody of anyone's money — it sits beside your node and
calls it on your behalf. The seed, the wallet password, and the bootstrap/admin
key documented here are *your* master credentials to *your own* system; protect
them accordingly.

Files in this directory are run on the host where you operate Conduit (the
reference deployment is a Hetzner VPS), not from a local clone.

## Runbook (first-time setup)

Assume Ubuntu 22.04+, root or a sudoer named `conduit`.

```bash
# 0. Fresh box hygiene
sudo apt update && sudo apt -y upgrade

# 1. Firewall (open SSH + Lightning P2P; deny everything else inbound)
sudo bash scripts/setup_firewall.sh

# 2. Bitcoin Core (pruned)
sudo bash scripts/install_bitcoind.sh         # installs + starts bitcoind.service
sudo cp bitcoind/bitcoin.conf.example /home/conduit/.bitcoin/bitcoin.conf
sudo nano /home/conduit/.bitcoin/bitcoin.conf  # set rpcpassword, prune size
sudo systemctl restart bitcoind

# 3. LND (mainnet + testnet on different ports)
sudo bash scripts/install_lnd.sh
sudo cp lnd/lnd.conf.example /home/conduit/.lnd/lnd.conf
sudo cp lnd/lnd-testnet.conf.example /home/conduit/.lnd-testnet/lnd.conf
sudo systemctl enable --now lnd lnd-testnet

# 4. Create the LND wallets (one-time, interactive)
lncli create                                   # SAVE THE SEED OFFLINE
lncli --network=testnet --rpcserver=127.0.0.1:10010 \
      --lnddir=/home/conduit/.lnd-testnet create

# 4b. (Optional) Auto-unlock the wallet on reboot — see "Wallet auto-unlock" below
sudo bash scripts/setup_wallet_unlock.sh             # mainnet
sudo bash scripts/setup_wallet_unlock.sh --testnet   # testnet (if desired)

# 5. Wait for chain sync (1–3 days). Check anytime:
bash scripts/verify_node.sh

# 6. Open Lightning channels
bash scripts/setup_channels.sh

# 7. Schedule the static channel backup off-box
crontab -e   # add: */15 * * * * bash /home/conduit/conduit/infra/scripts/backup_channels.sh

# 8. Schedule OFF-BOX Postgres backups via the systemd timer (with a
#    dead-man's switch). See "Scheduled off-box backups" below for the env file.
mkdir -p /home/conduit/backups/postgres
sudo install -m 0644 systemd/conduit-backup.service systemd/conduit-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now conduit-backup.timer
```

## Wallet auto-unlock

By default LND starts **locked** — after every reboot someone has to run
`lncli unlock` before the node (and therefore the Conduit API) can do
anything. That blocks unattended operation.

`scripts/setup_wallet_unlock.sh` configures LND to unlock itself on startup:
it prompts for the wallet password, writes it to
`/home/conduit/.lnd/wallet_password` with `0600` perms (owned by `conduit`),
and adds `wallet-unlock-password-file=...` to `lnd.conf`. Restart LND
(`sudo systemctl restart lnd`) to apply.

**Security tradeoff.** Auto-unlock trades convenience for risk: your wallet
password now lives on disk, so **anyone who gets root on your box can unlock
your wallet** and reach your funds. Use it only if you trust the box's disk
encryption and access controls. For high-value nodes, prefer a hardware-backed
unlock or keep running `lncli unlock` manually after each (rare) reboot.

## Postgres backups

`scripts/backup_postgres.sh` runs `pg_dump` against the production Postgres
container via `docker compose exec`, gzips the result to
`/home/conduit/backups/postgres/conduit_<timestamp>.sql.gz`, prunes dumps
older than 30 days, and logs success/failure to syslog (`logger -t
conduit-pg-backup`). It reads connection details and `POSTGRES_PASSWORD` from
the prod compose file + `.env.prod`.

For off-box durability, `scripts/backup_postgres_to_s3.sh` runs the same
local backup and then uploads the newest dump to an S3-compatible bucket
(e.g. Hetzner Object Storage) when `BACKUP_S3_BUCKET` is set:

```bash
BACKUP_S3_BUCKET=my-bucket \
AWS_ENDPOINT_URL=https://fsn1.your-objectstorage.com \
bash scripts/backup_postgres_to_s3.sh
```

Periodically restore a dump into a throwaway database to confirm the backups
are actually usable.

### Scheduled off-box backups + dead-man's switch

The off-box backup runs on a **systemd timer** (`systemd/conduit-backup.timer`
→ `conduit-backup.service`), not cron. It runs `backup_postgres_to_s3.sh` every
6 hours and, **only on success**, pings a [healthchecks.io](https://healthchecks.io)-style
dead-man's-switch URL. A failed run (or a box that's down, or a timer that never
fires) misses the ping, and the external monitor pages you. A backup that
*silently stops* is exactly the failure this catches.

Secrets/config live in a `0600` env file — **never in git** — read by the unit
via `EnvironmentFile=/etc/conduit/backup.env`:

```bash
# /etc/conduit/backup.env  (chmod 0600, owned by conduit)
BACKUP_S3_BUCKET=my-bucket
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_ENDPOINT_URL=https://fsn1.your-objectstorage.com   # for non-AWS providers
BACKUP_HEALTHCHECK_URL=https://hc-ping.com/<your-uuid> # the dead-man's switch
# optional overrides: REPO_DIR, ENV_FILE, BACKUP_DIR, RETENTION_DAYS, ...
```

Install and enable:

```bash
sudo mkdir -p /etc/conduit
sudo install -m 0600 -o conduit -g conduit /dev/stdin /etc/conduit/backup.env <<'EOF'
BACKUP_S3_BUCKET=my-bucket
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_ENDPOINT_URL=https://fsn1.your-objectstorage.com
BACKUP_HEALTHCHECK_URL=https://hc-ping.com/<your-uuid>
EOF

sudo install -m 0644 systemd/conduit-backup.service systemd/conduit-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now conduit-backup.timer

# Verify
systemctl list-timers conduit-backup.timer     # next/last run
sudo systemctl start conduit-backup.service     # run once now
journalctl -u conduit-backup.service -n 50      # check the last run
```

On the dead-man's-switch side, create a check (e.g. on healthchecks.io) with a
period of 6h and a grace window of ~1–2h, copy its ping URL into
`BACKUP_HEALTHCHECK_URL`, and point it at a pager/email. The unit also sends a
`/start` ping when a run begins and a `/fail` ping on error, so the monitor can
flag a *hung* backup and alert immediately on a *failed* one — not just a
*missing* one.

## Deploys & rollback

`scripts/deploy.sh` codifies the previously-manual "tar the image over SSH, load
it, migrate, recreate the api" process into one idempotent, health-gated command.
It snapshots the running image before promoting the new one, runs
`alembic upgrade head` (via the api entrypoint), recreates **only** the api,
waits for the deeper readiness probe (`/v1/health/ready`), reloads nginx, and
**auto-rolls-back** if the new container never goes ready.

Image-tag convention (matches the existing manual flow):

| Tag                        | Meaning |
| -------------------------- | ------- |
| `conduit/core:prod`        | what `docker-compose.prod.yml` runs ("current") |
| `conduit/core:prod-rollback` | the image that was current before the last deploy |
| `conduit/core:prod-vX.Y.Z` | immutable per-version archive tag (when `--version` is given) |

```bash
# On the box — rebuild from source and deploy:
bash scripts/deploy.sh deploy --build

# On the box — deploy a pinned image tar produced by `docker save`:
bash scripts/deploy.sh deploy --image-tar /tmp/conduit-core-1.2.3.tar --version 1.2.3

# Pull a registry tag and deploy:
bash scripts/deploy.sh deploy --pull ghcr.io/jake1848/conduit:1.2.3 --version 1.2.3

# Drive a REMOTE box over SSH (copies the script + tar, re-execs there):
DEPLOY_HOST=conduit@167.233.27.130 \
  bash scripts/deploy.sh deploy --image-tar /tmp/conduit-core-1.2.3.tar --version 1.2.3

# One-command rollback to the previously-deployed image:
bash scripts/deploy.sh rollback
```

A failed health gate during `deploy` triggers an automatic rollback to
`conduit/core:prod-rollback`; `deploy.sh rollback` does the same on demand. The
script is `set -euo pipefail`, every step is idempotent (safe to re-run), and it
reads the prod stack location from `REPO_DIR` / `COMPOSE_FILE` / `ENV_FILE`
(see the top of the script for all knobs).

## Platform fee configuration (your revenue)

Conduit charges a small **per-transaction platform fee**, in sats, on top of
each payment. This is *your* revenue as the operator — it settles to *your* own
node, since you hold the keys and the funds. Configure it on the Core API stack
(e.g. in `.env.prod`, which the prod compose file reads):

| Env                     | Default | Meaning |
| ----------------------- | ------- | ------- |
| `PLATFORM_FEE_PERCENT`  | `0.5`   | your fee, as a percent of the payment amount (`0.5` = 0.5%); set `0` to disable |
| `PLATFORM_FEE_MIN_SATS` | `1`     | floor for the per-transaction fee |
| `PLATFORM_FEE_MAX_SATS` | `1000`  | ceiling for the per-transaction fee |

The fee is charged on top of the payment amount (separate from the LND routing
fee) and is collected on settle. Set `PLATFORM_FEE_PERCENT=0` to run Conduit
with no platform fee. Track what you've earned via `GET /v1/metrics`.

## Security checklist

- [ ] LND seed phrase stored **only** on paper, off the VPS
- [ ] Wallet unlock handled: either manual `lncli unlock` after each reboot, or
      auto-unlock via `setup_wallet_unlock.sh` with its disk-exposure tradeoff understood
- [ ] If auto-unlock is enabled: `wallet_password` file is `0600`, owned by `conduit`
- [ ] LND gRPC (`10009`) and REST (`8080`) **never** appear in `ufw status` as ALLOW
- [ ] SSH password auth disabled in `/etc/ssh/sshd_config`: `PasswordAuthentication no`
- [ ] `fail2ban` installed
- [ ] `unattended-upgrades` enabled
- [ ] `admin.macaroon` file permissions = 600, owned by `conduit`
- [ ] Bootstrap/admin key (your master key to this deployment) stored in a secret
      manager, never committed, and rotated if it ever leaks
- [ ] Channel backup file (`channel.backup`) replicated to a separate host
- [ ] Off-box Postgres backups scheduled (`conduit-backup.timer`), restore-tested, and wired to a dead-man's switch (`BACKUP_HEALTHCHECK_URL`)
- [ ] `/etc/conduit/backup.env` is `0600`, owned by `conduit`, and never committed
- [ ] `vercel env` (or wherever the API key lives) restricted to the deployment env
- [ ] HTTPS via certbot in front of the Core API container

## Verifying the node

```bash
bash scripts/verify_node.sh
```

Prints sync status, channel count, wallet/channel balances.
