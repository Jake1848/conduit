#!/usr/bin/env bash
# Export the Static Channel Backup (SCB) and replicate it OFF-BOX.
#
# SCBs let you force-close all channels and recover funds if the LND data is
# lost. They MUST live somewhere other than this VPS — losing the SCB along
# with the node means losing the channels. This script therefore REFUSES to run
# unless an off-box destination is configured: a local-only SCB is a false sense
# of safety, so a misconfigured job fails loudly instead of silently doing nothing.
#
# Configure at least ONE destination via env (and optionally a dead-man's switch):
#   SCB_SCP_DEST=backup@host:/srv/lnd-backups/     [SCB_SCP_KEY=~/.ssh/backup_key]
#   SCB_S3_DEST=s3://my-encrypted-bucket/conduit/  [SCB_S3_SSE=aws:kms]
#   SCB_RCLONE_DEST=gdrive-crypt:lnd-backups/
#   SCB_HEALTHCHECK_URL=https://hc-ping.com/<uuid>   (pinged only on success)
#
#   bash scripts/backup_channels.sh
#   # cron (every 6h):  0 */6 * * * SCB_S3_DEST=... bash .../backup_channels.sh
set -euo pipefail

OUT_DIR="${BACKUP_DIR:-/home/conduit/backups}"
LNCLI="${LNCLI:-lncli}"

log()  { logger -t conduit-scb-backup "$*" 2>/dev/null || true; echo "$*"; }
fail() { log "FAILED: $*"; exit 1; }

# Refuse to run without an off-box destination — the whole point of an SCB is
# that it survives loss of this box.
if [[ -z "${SCB_SCP_DEST:-}" && -z "${SCB_S3_DEST:-}" && -z "${SCB_RCLONE_DEST:-}" ]]; then
  fail "no off-box destination set. Configure SCB_SCP_DEST, SCB_S3_DEST, or \
SCB_RCLONE_DEST — a SCB kept only on this VPS does NOT survive disk loss."
fi

mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$OUT_DIR/channel-backup-$STAMP.scb"

$LNCLI exportchanbackup --output_file="$OUT" || fail "lncli exportchanbackup failed"
chmod 600 "$OUT"
[[ -s "$OUT" ]] || fail "SCB export produced an empty file: $OUT"
log "exported SCB → $OUT ($(du -h "$OUT" | cut -f1))"

# Replicate off-box. Any configured destination must SUCCEED or the run fails.
replicated=0
if [[ -n "${SCB_SCP_DEST:-}" ]]; then
  scp ${SCB_SCP_KEY:+-i "$SCB_SCP_KEY"} -o BatchMode=yes "$OUT" "$SCB_SCP_DEST" \
    || fail "scp to $SCB_SCP_DEST failed"
  log "replicated via scp → $SCB_SCP_DEST"; replicated=1
fi
if [[ -n "${SCB_S3_DEST:-}" ]]; then
  aws s3 cp "$OUT" "$SCB_S3_DEST" --sse "${SCB_S3_SSE:-aws:kms}" \
    || fail "aws s3 cp to $SCB_S3_DEST failed"
  log "replicated via s3 → $SCB_S3_DEST"; replicated=1
fi
if [[ -n "${SCB_RCLONE_DEST:-}" ]]; then
  rclone copy "$OUT" "$SCB_RCLONE_DEST" || fail "rclone copy to $SCB_RCLONE_DEST failed"
  log "replicated via rclone → $SCB_RCLONE_DEST"; replicated=1
fi
[[ "$replicated" == "1" ]] || fail "no replication performed"

# Keep last 24 locally (the off-box copy is the source of truth).
ls -1t "$OUT_DIR"/channel-backup-*.scb 2>/dev/null | tail -n +25 | xargs -r rm -f

# Dead-man's switch: only pinged on a fully successful off-box replication, so a
# silently-failing SCB job trips the operator's "missing check-in" alert.
[[ -n "${SCB_HEALTHCHECK_URL:-}" ]] && curl -fsS -m 10 "$SCB_HEALTHCHECK_URL" >/dev/null 2>&1 || true
log "OK: SCB backed up and replicated off-box"
