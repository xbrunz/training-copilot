#!/bin/sh
# Runs once, on the first start of an empty Postgres volume.
# Creates two databases and three login roles with least privilege:
#   n8n             owns the "n8n" database (n8n's internal state)
#   copilot_writer  n8n's connection for run logs: insert/select, update only where needed, never delete
#   copilot_reader  KPI queries and dashboards: select only
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v n8n_pw="$N8N_DB_PASSWORD" \
  -v writer_pw="$COPILOT_WRITER_PASSWORD" \
  -v reader_pw="$COPILOT_READER_PASSWORD" <<'SQL'
CREATE ROLE n8n LOGIN PASSWORD :'n8n_pw';
CREATE DATABASE n8n OWNER n8n;
REVOKE ALL ON DATABASE n8n FROM PUBLIC;

CREATE ROLE copilot_writer LOGIN PASSWORD :'writer_pw';
CREATE ROLE copilot_reader LOGIN PASSWORD :'reader_pw';
CREATE DATABASE copilot;
REVOKE ALL ON DATABASE copilot FROM PUBLIC;
GRANT CONNECT ON DATABASE copilot TO copilot_writer, copilot_reader;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname copilot -f /sql/01_schema.sql
