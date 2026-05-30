#!/usr/bin/env bash
# Configure LND wallet auto-unlock so the node comes back after a reboot
# without a human running `lncli unlock`.
#
#   sudo bash scripts/setup_wallet_unlock.sh            # mainnet
#   sudo bash scripts/setup_wallet_unlock.sh --testnet  # testnet instance
#
# SECURITY TRADEOFF: the wallet password is written to disk (0600, owned by
# conduit). Anyone who gets root on this box can read it and unlock the wallet.
# Only use this if you trust the VPS disk encryption. For high-value nodes,
# prefer a hardware-backed unlock or keep doing manual `lncli unlock`.
set -euo pipefail

LND_USER="${LND_USER:-conduit}"
LND_DIR="/home/${LND_USER}/.lnd"
NETWORK="mainnet"

if [[ "${1:-}" == "--testnet" ]]; then
  LND_DIR="/home/${LND_USER}/.lnd-testnet"
  NETWORK="testnet"
fi

CONF="${LND_DIR}/lnd.conf"
PW_FILE="${LND_DIR}/wallet_password"

if [[ ! -d "$LND_DIR" ]]; then
  echo "error: $LND_DIR does not exist. Install/configure LND first." >&2
  exit 1
fi
if [[ ! -f "$CONF" ]]; then
  echo "error: $CONF not found. Copy lnd.conf.example into place first." >&2
  exit 1
fi

echo "Configuring auto-unlock for the ${NETWORK} LND wallet at ${LND_DIR}."
echo

# Read the password twice without echoing it.
read -r -s -p "LND wallet password: " PW1
echo
read -r -s -p "Confirm password:    " PW2
echo
if [[ "$PW1" != "$PW2" ]]; then
  echo "error: passwords do not match." >&2
  exit 1
fi
if [[ -z "$PW1" ]]; then
  echo "error: empty password." >&2
  exit 1
fi

# Write the password file with no trailing newline, locked down.
umask 077
printf '%s' "$PW1" > "$PW_FILE"
chmod 600 "$PW_FILE"
chown "${LND_USER}:${LND_USER}" "$PW_FILE"
unset PW1 PW2

# Add the directive to lnd.conf if it isn't already active. Insert it under the
# existing [Application Options] section rather than appending a duplicate
# section header.
if grep -Eq '^[[:space:]]*wallet-unlock-password-file=' "$CONF"; then
  echo "lnd.conf already has an active wallet-unlock-password-file directive — leaving it."
elif grep -Eq '^\[Application Options\]' "$CONF"; then
  TMP_CONF="$(mktemp)"
  awk -v line="wallet-unlock-password-file=${PW_FILE}" '
    { print }
    /^\[Application Options\]/ && !ins { print line; ins=1 }
  ' "$CONF" > "$TMP_CONF"
  cat "$TMP_CONF" > "$CONF"   # overwrite content, preserving original perms/owner
  rm -f "$TMP_CONF"
  echo "Added wallet-unlock-password-file=${PW_FILE} under [Application Options] in ${CONF}."
else
  printf '\n[Application Options]\nwallet-unlock-password-file=%s\n' "$PW_FILE" >> "$CONF"
  echo "Added wallet-unlock-password-file=${PW_FILE} to ${CONF} (new section)."
fi

echo
echo "Done. Restart LND to apply:"
if [[ "$NETWORK" == "testnet" ]]; then
  echo "  sudo systemctl restart lnd-testnet"
else
  echo "  sudo systemctl restart lnd"
fi
echo
echo "!!! SECURITY: ${PW_FILE} now contains your wallet password in plaintext"
echo "    (0600, owned by ${LND_USER}). Root on this box = wallet access."
