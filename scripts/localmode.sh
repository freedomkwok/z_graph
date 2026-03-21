#!/bin/sh
set -eu

SERVICE_NAME="postgres"

if [ -z "$(docker compose ps --services --status running "$SERVICE_NAME")" ]; then
  echo "PostgreSQL is not running. Starting Docker service: $SERVICE_NAME"
  docker compose up -d "$SERVICE_NAME"
else
  echo "PostgreSQL is already running."
fi

if [ "${1:-}" = "--check-only" ]; then
  exit 0
fi

echo "Starting local development mode..."
npm run dev
