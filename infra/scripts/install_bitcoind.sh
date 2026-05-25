#!/usr/bin/env bash
# Install Bitcoin Core (pruned mainnet) as a systemd service.
# Run as root on Ubuntu 22.04+.
set -euo pipefail

BITCOIN_VERSION="${BITCOIN_VERSION:-27.1}"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  TARBALL="bitcoin-${BITCOIN_VERSION}-x86_64-linux-gnu.tar.gz" ;;
  aarch64) TARBALL="bitcoin-${BITCOIN_VERSION}-aarch64-linux-gnu.tar.gz" ;;
  *) echo "Unsupported arch: $ARCH"; exit 1 ;;
esac

id -u conduit &>/dev/null || useradd -m -s /bin/bash conduit
install -d -o conduit -g conduit /home/conduit/.bitcoin

cd /tmp
curl -fsSLO "https://bitcoincore.org/bin/bitcoin-core-${BITCOIN_VERSION}/${TARBALL}"
curl -fsSLO "https://bitcoincore.org/bin/bitcoin-core-${BITCOIN_VERSION}/SHA256SUMS"
grep " ${TARBALL}\$" SHA256SUMS | sha256sum -c -

tar -xzf "$TARBALL"
install -m 0755 "bitcoin-${BITCOIN_VERSION}/bin/"{bitcoind,bitcoin-cli,bitcoin-tx} /usr/local/bin/

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
install -m 0644 "$SCRIPT_DIR/../bitcoind/bitcoind.service" /etc/systemd/system/bitcoind.service
systemctl daemon-reload
systemctl enable bitcoind

echo
echo "bitcoind installed at /usr/local/bin/bitcoind"
echo "Next: cp infra/bitcoind/bitcoin.conf.example /home/conduit/.bitcoin/bitcoin.conf"
echo "      edit rpcpassword, then: systemctl start bitcoind"
