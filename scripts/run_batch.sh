#!/bin/sh
# Start test runs inside n8n via the token-protected test-runner webhook.
# Each run sends a Telegram approval request and waits for your tap.
# Usage: ./scripts/run_batch.sh [all | s01_good_recovery_intervals,s03_short_sleep_hard_day | live] [guardrails.json]
set -eu
cd "$(dirname "$0")/.."
TOKEN=$(grep '^TEST_RUNNER_TOKEN=' .env | cut -d= -f2-)
printf 'header = "X-Test-Token: %s"\n' "$TOKEN" | curl -sS -K - \
  "http://127.0.0.1:5678/webhook/training-copilot-test-batch?scenarios=${1:-all}&guardrails=${2:-guardrails.json}"
echo
