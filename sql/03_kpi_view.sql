-- Migration 03: the run set every KPI is computed over.
-- Completed runs only, excluding loop-mechanics tests (rules_version 'TEST-ONLY').
SET search_path = copilot;

CREATE VIEW v_kpi_runs AS
SELECT s.*, r.rules_version
FROM v_run_summary s JOIN agent_runs r USING (run_id)
WHERE r.status = 'completed' AND r.rules_version IS DISTINCT FROM 'TEST-ONLY';

GRANT SELECT ON v_kpi_runs TO copilot_reader, copilot_writer;
