# Conduit infrastructure

Files in this directory are run on the Hetzner VPS, not from a local clone.

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

# 8. Schedule Postgres backups (production API stack)
mkdir -p /home/conduit/backups/postgres
crontab -e   # add: 0 */6 * * * bash /home/conduit/conduit/infra/scripts/backup_postgres.sh
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

**Security tradeoff.** Auto-unlock trades convenience for risk: the wallet
password now lives on disk, so **anyone who gets root on this VPS can unlock
the wallet**. Use it only if you trust the box's disk encryption and access
controls. For high-value nodes, prefer a hardware-backed unlock or keep
running `lncli unlock` manually after each (rare) reboot.

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

The local-only script is the default; periodically restore a dump into a
throwaway database to confirm the backups are actually usable.

> ⚠️ **Gap on the live box (as of the 0.6.0 audit):** only `backup_postgres.sh`
> (local) is scheduled — every dump lives on the same disk as the database it
> protects, so a disk/host loss takes both. The off-box `backup_postgres_to_s3.sh`
> exists but is **not yet scheduled** because no S3 bucket is provisioned. Once a
> bucket is available (e.g. Hetzner Object Storage), replace the cron with the S3
> variant (set `BACKUP_S3_BUCKET` + `AWS_ENDPOINT_URL` and credentials in a
> `0600` env file) so the ledger survives host loss. Consider a dead-man's-switch
> (e.g. healthchecks.io) that the backup pings, alerting if no off-box copy lands
> within ~12h.

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
- [ ] Channel backup file (`channel.backup`) replicated to a separate host
- [ ] Postgres backups scheduled (`backup_postgres.sh`) and restore-tested; off-box copy if value justifies it
- [ ] `vercel env` (or wherever the API key lives) restricted to the deployment env
- [ ] HTTPS via certbot in front of the Core API container

## Verifying the node

```bash
bash scripts/verify_node.sh
```

Prints sync status, channel count, wallet/channel balances.
