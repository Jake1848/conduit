#!/usr/bin/env bash
# Minimal on-box alerting for the money-path danger signals.
#
# Conduit COMPUTES solvency, LND chain-sync and worker-liveness and exposes them
# on the (internal, unauthenticated) Prometheus endpoint — but nothing watches
# them, so on a real-money ledger an insolvency or a dead invoice_watcher/
# reconciler surfaces only as a stdout line nobody reads. This script scrapes the
# internal /metrics and PAGES if anything is wrong. Run it from cron, e.g.:
#
#   * * * * * ALERT_WEBHOOK_URL=... METRICS_URL=http://127.0.0.1:8000/metrics \
#            bash /home/conduit/conduit/infra/scripts/alert_check.sh
#
# Wire ALERT_WEBHOOK_URL to your pager (PagerDuty Events API, Slack incoming
# webhook, healthchecks.io /fail, ntfy, etc.). Until it's set the script still
# logs to journald and exits non-zero, so a cron-failure mail / monitor catches it.
set -uo pipefail

# >>> OPERATOR: set this to your pager/Slack/PagerDuty webhook. <<<
ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL:-PLACEHOLDER_SET_ME}"
METRICS_URL="${METRICS_URL:-http://127.0.0.1:8000/metrics}"
# Page if the solvency monitor hasn't run in this many seconds (default 15m).
WORKER_STALE_SECONDS="${WORKER_STALE_SECONDS:-900}"

log() { logger -t conduit-alert "$*" 2>/dev/null || true; echo "$*"; }

metric() {  # metric <name> -> first numeric sample value (ignores labels), or empty
  awk -v n="$1" '$0 !~ /^#/ && index($0, n)==1 { print $NF; exit }' <<<"$METRICS"
}

PAGE=""
add() { PAGE="${PAGE:+$PAGE; }$1"; log "ALERT: $1"; }
# Prometheus renders gauges as floats ("0.0"/"1.0"), so compare NUMERICALLY.
is_zero() { [[ -n "$1" ]] && awk "BEGIN{exit !(($1)==0)}"; }
gt() { [[ -n "$1" ]] && awk "BEGIN{exit !(($1) > ($2))}"; }

METRICS="$(curl -fsS -m 10 "$METRICS_URL" 2>/dev/null)" || {
  add "metrics endpoint unreachable at $METRICS_URL (API down?)"
}

if [[ -n "$METRICS" ]]; then
  solvent="$(metric conduit_solvent)"
  synced="$(metric conduit_lnd_synced_to_chain)"
  # WORKER_LIVENESS is labeled per worker; take the largest staleness seen.
  worker_stale="$(awk '$0 !~ /^#/ && index($0,"conduit_worker_seconds_since_last_run")==1 {print $NF}' <<<"$METRICS" | sort -n | tail -1)"

  is_zero "$solvent" && add "INSOLVENT — conduit_solvent=0 (liabilities exceed node assets)"
  is_zero "$synced" && add "LND not synced to chain — conduit_lnd_synced_to_chain=0"
  gt "$worker_stale" "$WORKER_STALE_SECONDS" \
    && add "money-path worker stale — ${worker_stale%.*}s since last run (> ${WORKER_STALE_SECONDS}s)"
fi

if [[ -z "$PAGE" ]]; then
  exit 0   # all clear
fi

MSG="Conduit ALERT @ $(hostname): $PAGE"
if [[ "$ALERT_WEBHOOK_URL" != "PLACEHOLDER_SET_ME" ]]; then
  curl -fsS -m 10 -X POST -H "Content-Type: application/json" \
    -d "{\"text\":\"$MSG\"}" "$ALERT_WEBHOOK_URL" >/dev/null 2>&1 \
    || log "WARNING: failed to deliver alert to ALERT_WEBHOOK_URL"
else
  log "WARNING: ALERT_WEBHOOK_URL is the placeholder — alert NOT delivered to a pager. Set it."
fi
exit 1
