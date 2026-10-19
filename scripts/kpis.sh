#!/bin/sh
# Print the KPI report, connecting as the read-only copilot_reader role.
set -eu
cd "$(dirname "$0")/.."
docker compose exec -T postgres sh -c 'PGPASSWORD="$COPILOT_READER_PASSWORD" psql -h 127.0.0.1 -U copilot_reader -d copilot -q' < sql/kpis.sql
