#!/usr/bin/env bash
# Pull latest code + restart services. Run as the deploy user on the VPS:
#
#   ssh docpilot@YOUR-VPS-IP
#   cd ~/docpilot
#   ./deploy/deploy.sh
#
# Idempotent — safe to run multiple times.

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${APP_DIR}"

echo "▶ Pulling latest code"
git fetch origin
git checkout architecture-update
git pull --ff-only

echo "▶ Rebuilding images (cached layers reused)"
docker compose build

echo "▶ Applying DB migrations"
docker compose run --rm api alembic upgrade head

echo "▶ Restarting services"
docker compose up -d

echo "▶ Pruning old images"
docker image prune -f

echo "▶ Health check"
sleep 5
curl -fsS http://127.0.0.1:8000/ || {
  echo "✗ API did not respond on :8000 — check 'docker compose logs api'."
  exit 1
}

echo "✓ Deploy complete."
