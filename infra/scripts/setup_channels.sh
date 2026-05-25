#!/usr/bin/env bash
# Open initial Lightning channels on mainnet.
# Edit the PEERS array below before running.
set -euo pipefail

# Format: "pubkey@host:port,channel_sats"
PEERS=(
  # "03864ef025fde8fb587d989186ce6a4a186895ee44a926bfc370e2c366597a3f8f@3.33.236.230:9735,2000000"
  # "0237b0bb7d3eb7faf6c14e15f5c4f0a1a9e1cd1f0f4e96c8f9e5b2e2c1d8e8e7f6@somenode.xyz:9735,1000000"
)

if (( ${#PEERS[@]} == 0 )); then
  echo "Edit setup_channels.sh and add at least one peer before running." >&2
  exit 1
fi

for entry in "${PEERS[@]}"; do
  uri="${entry%,*}"
  sats="${entry##*,}"
  pubkey="${uri%@*}"
  host="${uri#*@}"

  echo "→ connecting to $uri"
  lncli connect "$uri" || true

  echo "→ opening ${sats} sat channel to $pubkey"
  lncli openchannel --node_key="$pubkey" --local_amt="$sats" --sat_per_vbyte=2
done
