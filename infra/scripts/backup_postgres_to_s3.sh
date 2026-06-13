#!/usr/bin/env bash
# Run the local Postgres backup, then upload the newest dump to an
# S3-compatible bucket (e.g. Hetzner Object Storage).
#
#   BACKUP_S3_BUCKET=my-bucket \
#   AWS_ENDPOINT_URL=https://fsn1.your-objectstorage.com \
#   bash scripts/backup_postgres_to_s3.sh
#
# Requires the awscli (`aws`) with credentials configured (env vars, ~/.aws,
# or an instance profile). Set AWS_ENDPOINT_URL for non-AWS providers.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/home/conduit/backups/postgres}"
S3_PREFIX="${BACKUP_S3_PREFIX:-conduit/postgres}"

log()  { logger -t conduit-pg-backup-s3 "$*"; echo "$*"; }
fail() { log "FAILED: $*"; exit 1; }

[[ -n "${BACKUP_S3_BUCKET:-}" ]] || fail "BACKUP_S3_BUCKET is not set"
command -v aws >/dev/null 2>&1 || fail "aws CLI not found on PATH"

# 1. Produce the local backup (also handles retention/pruning).
BACKUP_DIR="$BACKUP_DIR" bash "${SCRIPT_DIR}/backup_postgres.sh"

# 2. Upload the newest dump.
LATEST="$(find "$BACKUP_DIR" -name 'conduit_*.sql.gz' -type f -printf '%T@ %p\n' \
            | sort -nr | head -1 | cut -d' ' -f2-)"
[[ -n "$LATEST" ]] || fail "no local backup found to upload"

DEST="s3://${BACKUP_S3_BUCKET}/${S3_PREFIX}/$(basename "$LATEST")"
ENDPOINT_ARG=()
[[ -n "${AWS_ENDPOINT_URL:-}" ]] && ENDPOINT_ARG=(--endpoint-url "$AWS_ENDPOINT_URL")

log "uploading ${LATEST} → ${DEST}"
# Encrypt at rest (the dump is the entire agent ledger = real liabilities).
# SSE-S3 (AES256) needs no KMS key and works on S3 + most S3-compatible stores;
# override S3_SSE (e.g. "aws:kms") or set it empty if your endpoint lacks it. (M10)
S3_SSE="${S3_SSE:-AES256}"
SSE_ARG=(); [[ -n "$S3_SSE" ]] && SSE_ARG=(--sse "$S3_SSE")
if aws "${ENDPOINT_ARG[@]}" s3 cp "$LATEST" "$DEST" "${SSE_ARG[@]}"; then
  log "OK: uploaded ${DEST}${S3_SSE:+ (sse=$S3_SSE)}"
else
  fail "s3 upload failed"
fi
