#!/usr/bin/env bash
# Export and replicate the Static Channel Backup off-box.
#
# Static Channel Backups (SCBs) let you force-close all your channels and
# recover funds if the LND data is lost. They MUST be kept somewhere other
# than the VPS — losing the SCB along with the node means losing the channels.
set -euo pipefail

OUT_DIR="${BACKUP_DIR:-/home/conduit/backups}"
mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$OUT_DIR/channel-backup-$STAMP.scb"

lncli exportchanbackup --output_file="$OUT"
chmod 600 "$OUT"

# Replicate. Pick ONE — uncomment and configure:
# 1. SCP to a backup host:
#   scp -i ~/.ssh/backup_key "$OUT" backup@backup.example.com:/srv/lnd-backups/
# 2. Encrypted upload to S3:
#   aws s3 cp "$OUT" s3://my-encrypted-bucket/conduit/ --sse aws:kms
# 3. Rclone to encrypted remote:
#   rclone copy "$OUT" gdrive-crypt:lnd-backups/

# Keep last 24 locally.
ls -1t "$OUT_DIR"/channel-backup-*.scb 2>/dev/null | tail -n +25 | xargs -r rm -f
