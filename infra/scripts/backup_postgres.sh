#!/usr/bin/env bash
# Dump the Conduit Postgres database to a gzipped file and prune old backups.
#
#   bash scripts/backup_postgres.sh
#
# Designed for cron, e.g. every 6 hours:
#   0 */6 * * * bash /home/conduit/conduit/infra/scripts/backup_postgres.sh
#
# Reads connection details from the production compose stack. Override any of
# the env vars below to point elsewhere.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/conduit/conduit}"
COMPOSE_FILE="${COMPOSE_FILE:-${REPO_DIR}/docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-${REPO_DIR}/.env.prod}"
PG_SERVICE="${PG_SERVICE:-postgres}"
PG_USER="${PG_USER:-conduit}"
PG_DB="${PG_DB:-conduit}"
BACKUP_DIR="${BACKUP_DIR:-/home/conduit/backups/postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

log()  { logger -t conduit-pg-backup "$*"; echo "$*"; }
fail() { log "FAILED: $*"; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker not found on PATH"
[[ -f "$COMPOSE_FILE" ]] || fail "compose file not found: $COMPOSE_FILE"

# The prod compose uses ${POSTGRES_PASSWORD:?...}, so docker compose needs the
# env file to even parse. Pull the password out for PGPASSWORD too.
#
# pg_dump connects over the container's local unix socket, so on a default
# postgres image (local `trust` auth) no password is needed — but if the image
# requires one we must hand pg_dump the SAME value docker compose used. Compose
# strips one pair of surrounding quotes from an env-file value, so we do too;
# otherwise `POSTGRES_PASSWORD="s3cr3t"` would leave us authenticating as the
# literal `"s3cr3t"` and every backup would silently fail.
PGPASSWORD_VALUE=""
if [[ -f "$ENV_FILE" ]]; then
  PGPASSWORD_VALUE="$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
  if [[ "$PGPASSWORD_VALUE" == \"*\" || "$PGPASSWORD_VALUE" == \'*\' ]]; then
    PGPASSWORD_VALUE="${PGPASSWORD_VALUE:1:-1}"
  fi
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="${BACKUP_DIR}/conduit_${STAMP}.sql.gz"
TMP="${OUT}.tmp"

log "starting pg_dump of ${PG_DB} → ${OUT}"

# Stream pg_dump → gzip to a temp file, then atomically rename so a partial
# dump never leaves a corrupt "latest" backup. pipefail makes a pg_dump error
# fail the whole pipeline.
if docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T \
      -e PGPASSWORD="$PGPASSWORD_VALUE" \
      "$PG_SERVICE" pg_dump -U "$PG_USER" -d "$PG_DB" \
      | gzip -c > "$TMP"; then
  mv "$TMP" "$OUT"
  SIZE="$(du -h "$OUT" | cut -f1)"
  log "OK: wrote ${OUT} (${SIZE})"
else
  rm -f "$TMP"
  fail "pg_dump pipeline failed"
fi

# Prune backups older than RETENTION_DAYS. A prune hiccup must not fail the
# script after a successful dump, so swallow errors here (pipefail is on).
DELETED="$(find "$BACKUP_DIR" -name 'conduit_*.sql.gz' -type f -mtime "+${RETENTION_DAYS}" -print -delete 2>/dev/null | wc -l || true)"
log "pruned ${DELETED} backup(s) older than ${RETENTION_DAYS} days"
