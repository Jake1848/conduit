#!/bin/bash
# Container entrypoint: apply Alembic migrations, then start uvicorn.
# Migrations are idempotent — running this on every boot is safe and is the
# only path that schema changes reach production.
set -euo pipefail

cd /app

echo "[entrypoint] applying alembic migrations..."
alembic upgrade head

echo "[entrypoint] starting uvicorn..."
exec uvicorn conduit_core.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips='*'
