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

# 5. Wait for chain sync (1–3 days). Check anytime:
bash scripts/verify_node.sh

# 6. Open Lightning channels
bash scripts/setup_channels.sh

# 7. Schedule the static channel backup off-box
crontab -e   # add: */15 * * * * bash /home/conduit/conduit/infra/scripts/backup_channels.sh
```

## Security checklist

- [ ] LND seed phrase stored **only** on paper, off the VPS
- [ ] `lncli unlock` performed manually after each reboot (or use a hardware-backed unlock)
- [ ] LND gRPC (`10009`) and REST (`8080`) **never** appear in `ufw status` as ALLOW
- [ ] SSH password auth disabled in `/etc/ssh/sshd_config`: `PasswordAuthentication no`
- [ ] `fail2ban` installed
- [ ] `unattended-upgrades` enabled
- [ ] `admin.macaroon` file permissions = 600, owned by `conduit`
- [ ] Channel backup file (`channel.backup`) replicated to a separate host
- [ ] `vercel env` (or wherever the API key lives) restricted to the deployment env
- [ ] HTTPS via certbot in front of the Core API container

## Verifying the node

```bash
bash scripts/verify_node.sh
```

Prints sync status, channel count, wallet/channel balances.
