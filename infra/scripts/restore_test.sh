#!/usr/bin/env bash
# Prove a Postgres backup is actually restorable — the one DR assumption a
# real-money ledger can't afford to leave untested.
#
#   bash scripts/restore_test.sh                 # newest dump in BACKUP_DIR
#   DUMP=/path/to/conduit_YYYY.sql.gz bash scripts/restore_test.sh
#
# Restores the dump into a THROWAWAY database (never the live one), asserts the
# core ledger tables are present and reports their row counts, then drops the
# throwaway DB. Exit 0 = restore proven; non-zero = backups are NOT trustworthy.
#
# Designed to run alongside the backup cron, e.g. monthly:
#   0 5 1 * * bash /home/conduit/conduit/infra/scripts/restore_test.sh
#
# Reads the same connection details as backup_postgres.sh; override via env.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/conduit/conduit}"
COMPOSE_FILE="${COMPOSE_FILE:-${REPO_DIR}/docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-${REPO_DIR}/.env.prod}"
PG_SERVICE="${PG_SERVICE:-postgres}"
PG_USER="${PG_USER:-conduit}"
BACKUP_DIR="${BACKUP_DIR:-/home/conduit/backups/postgres}"
DUMP="${DUMP:-}"
TEST_DB="${TEST_DB:-conduit_restore_test_$$}"
# Tables that MUST exist in a usable ledger backup.
REQUIRED_TABLES="${REQUIRED_TABLES:-agents api_keys transactions}"
# Optional: a healthchecks.io-style dead-man's-switch URL pinged only on success.
HEALTHCHECK_URL="${HEALTHCHECK_URL:-}"

log()  { logger -t conduit-restore-test "$*" 2>/dev/null || true; echo "$*"; }
fail() { log "FAILED: $*"; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker not found on PATH"
[[ -f "$COMPOSE_FILE" ]] || fail "compose file not found: $COMPOSE_FILE"

# Same PGPASSWORD handling as backup_postgres.sh: explicit override wins,
# otherwise pull it out of the env file (compose strips one pair of quotes).
PGPASSWORD_VALUE="${PG_PASSWORD:-}"
if [[ -z "$PGPASSWORD_VALUE" && -f "$ENV_FILE" ]]; then
  PGPASSWORD_VALUE="$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
  if [[ "$PGPASSWORD_VALUE" == \"*\" || "$PGPASSWORD_VALUE" == \'*\' ]]; then
    PGPASSWORD_VALUE="${PGPASSWORD_VALUE:1:-1}"
  fi
fi

# Resolve the dump to test: explicit DUMP, else the newest in BACKUP_DIR.
if [[ -z "$DUMP" ]]; then
  DUMP="$(find "$BACKUP_DIR" -name 'conduit_*.sql.gz' -type f -printf '%T@ %p\n' 2>/dev/null \
          | sort -nr | head -1 | cut -d' ' -f2- || true)"
fi
[[ -n "$DUMP" && -f "$DUMP" ]] || fail "no dump found (DUMP unset and none in ${BACKUP_DIR})"

log "restore-test of ${DUMP} → throwaway DB ${TEST_DB}"

# gzip integrity first — never trust a dump that won't even decompress.
gzip -t "$DUMP" 2>/dev/null || fail "dump failed gzip integrity check: ${DUMP}"

# Only pass --env-file when one exists: the prod/mainnet composes interpolate
# ${POSTGRES_PASSWORD} and need it; the regtest compose inlines the password.
COMPOSE_ARGS=(-f "$COMPOSE_FILE")
[[ -f "$ENV_FILE" ]] && COMPOSE_ARGS+=(--env-file "$ENV_FILE")
dc() { docker compose "${COMPOSE_ARGS[@]}" exec -T \
         -e PGPASSWORD="$PGPASSWORD_VALUE" "$PG_SERVICE" "$@"; }

# Always drop the throwaway DB on exit, even if an assertion fails mid-way.
cleanup() {
  dc psql -U "$PG_USER" -d postgres -q \
     -c "DROP DATABASE IF EXISTS \"$TEST_DB\" WITH (FORCE);" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Fresh throwaway DB.
dc psql -U "$PG_USER" -d postgres -v ON_ERROR_STOP=1 -q \
   -c "DROP DATABASE IF EXISTS \"$TEST_DB\" WITH (FORCE);" \
   -c "CREATE DATABASE \"$TEST_DB\";" \
   || fail "could not create throwaway DB ${TEST_DB}"

# Restore the gzipped plain-SQL dump into it.
if ! gunzip -c "$DUMP" | dc psql -U "$PG_USER" -d "$TEST_DB" -v ON_ERROR_STOP=1 -q; then
  fail "restore of ${DUMP} into ${TEST_DB} errored"
fi

# Assert each required table exists and report its row count.
ok=1
for t in $REQUIRED_TABLES; do
  if n="$(dc psql -U "$PG_USER" -d "$TEST_DB" -tAc "SELECT count(*) FROM \"$t\";" 2>/dev/null)"; then
    n="$(echo "$n" | tr -d '[:space:]')"
    log "  table ${t}: ${n} rows"
  else
    log "  table ${t}: MISSING"
    ok=0
  fi
done
[[ "$ok" == "1" ]] || fail "restore completed but a required table is missing — backup is NOT usable"

log "OK: ${DUMP} restored cleanly; all required tables present (${REQUIRED_TABLES})"
[[ -n "$HEALTHCHECK_URL" ]] && curl -fsS -m 10 "$HEALTHCHECK_URL" >/dev/null 2>&1 || true
exit 0
