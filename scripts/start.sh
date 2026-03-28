#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "Starting Postgres..."
docker compose up -d

echo "Waiting for Postgres to be ready..."
until docker compose exec -T db pg_isready -U boxboxbox > /dev/null 2>&1; do
  sleep 1
done
echo "Postgres is ready."

echo "Running migrations..."
dotenvx run -- uv run alembic upgrade head

echo "Starting box-box-box..."
exec dotenvx run -- uv run python -m boxboxbox
