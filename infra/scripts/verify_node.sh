#!/usr/bin/env bash
# Quick health check across the Bitcoin + LND stack.
set -euo pipefail

echo "=== Bitcoin Core ==="
bitcoin-cli getblockchaininfo \
  | jq '{chain, blocks, headers, verificationprogress, pruned}'

echo
echo "=== LND (mainnet) ==="
lncli getinfo | jq '{alias, identity_pubkey, block_height, synced_to_chain, num_active_channels, num_pending_channels}'
lncli walletbalance | jq '.'
lncli channelbalance | jq '.'

if systemctl is-active --quiet lnd-testnet; then
  echo
  echo "=== LND (testnet) ==="
  lncli --rpcserver=127.0.0.1:10010 --lnddir=/home/conduit/.lnd-testnet getinfo \
    | jq '{alias, block_height, synced_to_chain, num_active_channels}'
fi
