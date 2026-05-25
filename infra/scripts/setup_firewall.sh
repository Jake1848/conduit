#!/usr/bin/env bash
set -euo pipefail

# Locks the box down: SSH + Bitcoin/Lightning P2P only.
# Run as root.

apt-get install -y ufw fail2ban

ufw --force reset
ufw default deny incoming
ufw default allow outgoing

ufw allow ssh
ufw allow 9735/tcp comment 'Lightning P2P (mainnet)'
ufw allow 9736/tcp comment 'Lightning P2P (testnet)'
ufw allow 8333/tcp comment 'Bitcoin P2P'

# Allow ONLY the nginx-fronted API:
ufw allow 80/tcp comment 'HTTP (cert renewal redirect)'
ufw allow 443/tcp comment 'HTTPS (Conduit API)'

# Never expose these:
#   10009 / 10010 — LND gRPC
#   8080  / 8081  — LND REST
#   8332          — bitcoind RPC
#   28332 / 28333 — bitcoind ZMQ

ufw --force enable
ufw status verbose

systemctl enable --now fail2ban
