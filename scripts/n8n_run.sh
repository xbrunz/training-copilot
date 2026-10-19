#!/bin/sh
# Run a workflow once via the n8n CLI and print a per-node summary.
# Usage: ./scripts/n8n_run.sh <workflow-id>
set -eu
cd "$(dirname "$0")/.."
docker compose exec -T -e N8N_RUNNERS_BROKER_PORT=5690 n8n n8n execute --id "$1" --rawOutput 2>/dev/null \
  | python3 -I scripts/summarize_run.py
