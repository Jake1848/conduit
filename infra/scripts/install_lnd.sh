#!/usr/bin/env bash
# Install LND (mainnet + testnet) as systemd services.
# Run as root on Ubuntu 22.04+.
set -euo pipefail

LND_VERSION="${LND_VERSION:-v0.18.4-beta}"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  TARBALL="lnd-linux-amd64-${LND_VERSION}.tar.gz" ;;
  aarch64) TARBALL="lnd-linux-arm64-${LND_VERSION}.tar.gz" ;;
  *) echo "Unsupported arch: $ARCH"; exit 1 ;;
esac

id -u conduit &>/dev/null || useradd -m -s /bin/bash conduit
install -d -o conduit -g conduit /home/conduit/.lnd /home/conduit/.lnd-testnet

cd /tmp
curl -fsSLO "https://github.com/lightningnetwork/lnd/releases/download/${LND_VERSION}/${TARBALL}"
curl -fsSLO "https://github.com/lightningnetwork/lnd/releases/download/${LND_VERSION}/manifest-${LND_VERSION}.txt"
grep " ${TARBALL}\$" "manifest-${LND_VERSION}.txt" | sha256sum -c -

DIR="lnd-linux-${ARCH/x86_64/amd64}${ARCH/aarch64/arm64}-${LND_VERSION}"
DIR="${DIR/x86_64/amd64}"; DIR="${DIR/aarch64/arm64}"
tar -xzf "$TARBALL"
install -m 0755 "$DIR"/{lnd,lncli} /usr/local/bin/

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
install -m 0644 "$SCRIPT_DIR/../lnd/lnd.service" /etc/systemd/system/lnd.service
install -m 0644 "$SCRIPT_DIR/../lnd/lnd-testnet.service" /etc/systemd/system/lnd-testnet.service
systemctl daemon-reload

echo
echo "lnd installed at /usr/local/bin/lnd"
echo "Next: copy lnd.conf.example into /home/conduit/.lnd/lnd.conf,"
echo "      then run: systemctl enable --now lnd"
echo "      then create wallet: lncli create     (SAVE SEED OFFLINE!)"
