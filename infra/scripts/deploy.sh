#!/usr/bin/env bash
# Idempotent Conduit deploy / rollback for the prod stack.
#
# Codifies the previously-manual "tar the image over SSH, load it, migrate,
# recreate the api" dance into one repeatable, safe command. It:
#   1. gets a new image onto the box (load a pinned tar, pull a registry tag,
#      OR rebuild from ./core),
#   2. snapshots the current prod image as the rollback tag,
#   3. runs `alembic upgrade head` (via the api entrypoint),
#   4. recreates ONLY the api service and health-gates it on /v1/health/ready,
#   5. reloads nginx,
#   6. and on a failed health-gate, auto-rolls-back to the previous image.
#
# It can run ON the box, or drive a remote box over SSH (DEPLOY_HOST=...): in
# that mode it copies itself (and an optional image tar) over and re-execs there.
#
# ---------------------------------------------------------------------------
# USAGE
#   # On the box, rebuild from source and deploy:
#   bash infra/scripts/deploy.sh deploy --build
#
#   # On the box, deploy a pinned image tar (from `docker save`):
#   bash infra/scripts/deploy.sh deploy --image-tar /tmp/conduit-core-1.2.3.tar --version 1.2.3
#
#   # Pull a registry tag and deploy:
#   bash infra/scripts/deploy.sh deploy --pull ghcr.io/jake1848/conduit:1.2.3 --version 1.2.3
#
#   # Drive a remote box over SSH (copies this script + tar, re-execs there):
#   DEPLOY_HOST=conduit@167.233.27.130 \
#     bash infra/scripts/deploy.sh deploy --image-tar /tmp/conduit-core-1.2.3.tar --version 1.2.3
#
#   # One-command rollback to the previously-deployed image:
#   bash infra/scripts/deploy.sh rollback
#
# ---------------------------------------------------------------------------
# IMAGE TAG CONVENTION (matches the existing manual process)
#   conduit/core:prod          -> what docker-compose.prod.yml runs ("current")
#   conduit/core:prod-rollback -> the image that was "current" before this deploy
#   conduit/core:prod-vX.Y.Z   -> immutable, per-version archive tag (when --version is given)
# A deploy retags the old :prod as :prod-rollback before promoting the new image
# to :prod; `rollback` just promotes :prod-rollback back to :prod and recreates.
#
# Safe by construction: set -euo pipefail, every step is idempotent, and a new
# api that won't pass /v1/health/ready is automatically reverted.
set -euo pipefail

# ---------------------------------------------------------------------------
# Config (override via env or flags)
# ---------------------------------------------------------------------------
REPO_DIR="${REPO_DIR:-/home/conduit/conduit}"
COMPOSE_FILE="${COMPOSE_FILE:-${REPO_DIR}/docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-${REPO_DIR}/.env.prod}"

IMAGE="${IMAGE:-conduit/core}"            # base image name (matches compose `image:`)
PROD_TAG="${PROD_TAG:-${IMAGE}:prod}"     # the tag compose actually runs
ROLLBACK_TAG="${ROLLBACK_TAG:-${IMAGE}:prod-rollback}"
API_SERVICE="${API_SERVICE:-api}"
NGINX_SERVICE="${NGINX_SERVICE:-nginx}"

# Health-gate tuning. We probe the api container directly (it publishes on
# 127.0.0.1:8000) for the DEEPER readiness endpoint, which checks the DB.
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/v1/health/ready}"
HEALTH_RETRIES="${HEALTH_RETRIES:-30}"    # 30 * 3s = 90s max wait
HEALTH_INTERVAL="${HEALTH_INTERVAL:-3}"

# Remote-drive: if set, we run ourselves over SSH on this host instead.
DEPLOY_HOST="${DEPLOY_HOST:-}"            # e.g. conduit@167.233.27.130
SSH="${SSH:-ssh}"
SCP="${SCP:-scp}"

log()  { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[deploy] WARN:\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m[deploy] FAILED:\033[0m %s\n' "$*" >&2; exit 1; }

# `docker compose` for the prod stack, always with the env file (the compose
# file uses ${VAR:?...} guards that won't even parse without it).
dc() { docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"; }

usage() {
  sed -n '2,46p' "$0"
  exit "${1:-0}"
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
CMD="${1:-}"; shift || true
BUILD=0
IMAGE_TAR=""
PULL_REF=""
VERSION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build)      BUILD=1 ;;
    --image-tar)  IMAGE_TAR="${2:?--image-tar needs a path}"; shift ;;
    --pull)       PULL_REF="${2:?--pull needs an image ref}"; shift ;;
    --version)    VERSION="${2:?--version needs X.Y.Z}"; shift ;;
    -h|--help)    usage 0 ;;
    *)            fail "unknown arg: $1 (try --help)" ;;
  esac
  shift
done

# ---------------------------------------------------------------------------
# Remote drive: copy this script (+ tar) to the box and re-exec there.
# ---------------------------------------------------------------------------
maybe_remote() {
  [[ -z "$DEPLOY_HOST" ]] && return 0   # we're already on the box

  log "remote deploy → ${DEPLOY_HOST}"
  local remote_script="/tmp/conduit-deploy.$$.sh"
  $SCP "$0" "${DEPLOY_HOST}:${remote_script}"

  local remote_tar_arg=()
  if [[ -n "$IMAGE_TAR" ]]; then
    local remote_tar="/tmp/$(basename "$IMAGE_TAR")"
    log "copying image tar → ${DEPLOY_HOST}:${remote_tar}"
    $SCP "$IMAGE_TAR" "${DEPLOY_HOST}:${remote_tar}"
    remote_tar_arg=(--image-tar "$remote_tar")
  fi

  local v_arg=(); [[ -n "$VERSION" ]] && v_arg=(--version "$VERSION")
  local b_arg=(); [[ "$BUILD" == "1" ]] && b_arg=(--build)
  local p_arg=(); [[ -n "$PULL_REF" ]] && p_arg=(--pull "$PULL_REF")

  # Re-exec on the box with DEPLOY_HOST cleared so it runs locally there.
  # shellcheck disable=SC2029  # we WANT the args expanded locally.
  $SSH "$DEPLOY_HOST" "DEPLOY_HOST= REPO_DIR='${REPO_DIR}' bash ${remote_script} ${CMD} ${b_arg[*]} ${p_arg[*]} ${remote_tar_arg[*]} ${v_arg[*]}; rc=\$?; rm -f ${remote_script}; exit \$rc"
  exit $?
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
preflight() {
  command -v docker >/dev/null 2>&1 || fail "docker not found on PATH"
  [[ -f "$COMPOSE_FILE" ]] || fail "compose file not found: $COMPOSE_FILE"
  [[ -f "$ENV_FILE" ]]     || fail "env file not found: $ENV_FILE"
}

image_exists() { docker image inspect "$1" >/dev/null 2>&1; }

# Snapshot whatever is currently :prod as the rollback tag (idempotent).
snapshot_current() {
  if image_exists "$PROD_TAG"; then
    log "snapshotting current ${PROD_TAG} → ${ROLLBACK_TAG}"
    docker tag "$PROD_TAG" "$ROLLBACK_TAG"
  else
    warn "no existing ${PROD_TAG} to snapshot (first deploy?) — rollback won't be available"
  fi
}

# Get the NEW image onto the box and tag it as :prod (+ optional :prod-vX.Y.Z).
stage_new_image() {
  if [[ -n "$IMAGE_TAR" ]]; then
    [[ -f "$IMAGE_TAR" ]] || fail "image tar not found: $IMAGE_TAR"
    log "loading image from tar: $IMAGE_TAR"
    # `docker load` prints "Loaded image: <ref>"; capture it so we can retag.
    local loaded
    loaded="$(docker load -i "$IMAGE_TAR" | sed -n 's/^Loaded image: //p' | head -1)"
    [[ -n "$loaded" ]] || fail "could not determine loaded image ref from tar"
    log "loaded ${loaded}"
    docker tag "$loaded" "$PROD_TAG"
  elif [[ -n "$PULL_REF" ]]; then
    log "pulling ${PULL_REF}"
    docker pull "$PULL_REF"
    docker tag "$PULL_REF" "$PROD_TAG"
  elif [[ "$BUILD" == "1" ]]; then
    log "building ${PROD_TAG} from ${REPO_DIR}/core"
    dc build "$API_SERVICE"   # compose tags it as conduit/core:prod per the compose file
  else
    fail "no image source: pass --build, --image-tar <path>, or --pull <ref>"
  fi

  # Immutable per-version archive tag for easy targeted rollback later.
  if [[ -n "$VERSION" ]]; then
    log "tagging archive ${IMAGE}:prod-v${VERSION}"
    docker tag "$PROD_TAG" "${IMAGE}:prod-v${VERSION}"
  fi
}

# Recreate the api (its entrypoint runs `alembic upgrade head` on boot) and wait
# for the deeper readiness probe. Returns non-zero if it never goes ready.
recreate_and_gate() {
  log "running migrations + recreating ${API_SERVICE} (entrypoint applies 'alembic upgrade head')"
  # --force-recreate so the container is rebuilt from the freshly-tagged image
  # even if compose thinks nothing changed; idempotent to re-run.
  dc up -d --no-deps --force-recreate "$API_SERVICE"

  # Re-point nginx at the freshly-recreated container immediately (its IP
  # changed on recreate). Without this, nginx proxies to the destroyed old
  # container for the WHOLE health-gate window → up to ~90s of edge 502s (audit
  # H6). Doing it now shrinks the only 502 window to the new api's boot/migrate
  # time. Best-effort; the gate below still rolls back if it never goes ready.
  reload_nginx || warn "nginx reload right after recreate failed (will retry post-gate)"

  log "health-gating on ${HEALTH_URL} (up to $((HEALTH_RETRIES * HEALTH_INTERVAL))s)"
  local i
  for ((i = 1; i <= HEALTH_RETRIES; i++)); do
    # /v1/health/ready returns 200 only when the DB is reachable (the money
    # path's hard dependency). curl --fail makes any non-2xx a non-zero exit.
    if curl -fsS -m 5 "$HEALTH_URL" >/dev/null 2>&1; then
      log "api is READY (after ${i} probe(s))"
      return 0
    fi
    sleep "$HEALTH_INTERVAL"
  done
  return 1
}

reload_nginx() {
  # nginx proxies to the api by compose-service name; recreating the api can
  # change its container IP, so nudge nginx to re-resolve. Reload (graceful, no
  # dropped connections) if the container is up; otherwise (re)start it.
  if dc ps "$NGINX_SERVICE" --status running >/dev/null 2>&1 \
     && [[ -n "$(dc ps -q "$NGINX_SERVICE" 2>/dev/null)" ]]; then
    log "reloading ${NGINX_SERVICE} (nginx -s reload)"
    if ! dc exec -T "$NGINX_SERVICE" nginx -s reload 2>/dev/null; then
      warn "graceful reload failed; recreating ${NGINX_SERVICE}"
      dc up -d --no-deps "$NGINX_SERVICE"
    fi
  else
    log "starting ${NGINX_SERVICE}"
    dc up -d --no-deps "$NGINX_SERVICE"
  fi
}

# Promote :prod-rollback back to :prod and recreate the api.
do_rollback() {
  image_exists "$ROLLBACK_TAG" || fail "no ${ROLLBACK_TAG} image to roll back to"
  log "rolling back: ${ROLLBACK_TAG} → ${PROD_TAG}"
  docker tag "$ROLLBACK_TAG" "$PROD_TAG"
  if recreate_and_gate; then
    reload_nginx
    log "rollback complete — api is serving the previous image"
  else
    fail "rollback recreated the api but it did NOT pass the health gate; investigate manually (check 'docker compose -f $COMPOSE_FILE logs $API_SERVICE')"
  fi
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
cmd_deploy() {
  preflight
  snapshot_current          # so rollback has a target if the new image is bad
  stage_new_image
  if recreate_and_gate; then
    reload_nginx
    log "DEPLOY OK — ${PROD_TAG} is live and ready${VERSION:+ (archived as ${IMAGE}:prod-v${VERSION})}"
  else
    warn "new api FAILED the health gate; auto-rolling-back"
    if image_exists "$ROLLBACK_TAG"; then
      do_rollback
      fail "deploy aborted and rolled back to the previous image"
    else
      fail "deploy failed the health gate and there is NO rollback image; api may be down — check 'docker compose -f $COMPOSE_FILE logs $API_SERVICE'"
    fi
  fi
}

cmd_rollback() {
  preflight
  do_rollback
}

# Remote-drive must happen AFTER arg parsing but BEFORE we touch local docker.
maybe_remote

case "$CMD" in
  deploy)   cmd_deploy ;;
  rollback) cmd_rollback ;;
  ""|-h|--help) usage 0 ;;
  *)        fail "unknown command: '$CMD' (expected: deploy | rollback; see --help)" ;;
esac
