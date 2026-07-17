#!/bin/sh
# Container entrypoint: bring the schema up to date, then serve.
# Running migrations here (not create_all) makes Alembic the source of truth in production.
# create_all still runs on app startup as an idempotent safety net for zero-setup/demo modes.
set -e

echo "[entrypoint] applying database migrations (alembic upgrade head)…"
alembic upgrade head || {
  echo "[entrypoint] WARNING: alembic upgrade failed; the app's create_all will still bootstrap tables."
}

echo "[entrypoint] starting uvicorn on port ${PORT:-8080}…"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
