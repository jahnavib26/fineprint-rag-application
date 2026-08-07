#!/bin/sh
# Migrate, then serve. Running migrations here rather than in a separate
# release step keeps single-container hosts (Fly, Render, Railway, Cloud Run)
# to one moving part; alembic is idempotent, so a restart or a second replica
# is harmless.
set -e

echo "==> running migrations"
alembic upgrade head

echo "==> starting FinePrint on :${PORT:-8000}"
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --proxy-headers \
  --forwarded-allow-ips '*'
