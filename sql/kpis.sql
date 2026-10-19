-- Training Copilot KPIs. Run as the read-only role:
--   ./scripts/kpis.sh
-- Scope: view v_kpi_runs (completed runs, loop-mechanics tests excluded; see 03_kpi_view.sql).
SET search_path = copilot;

\echo '== 1. Headline KPIs (by data source)'
SELECT coalesce(data_source, 'all') AS data_source,
       count(*)                                                                   AS runs,
       round(100.0 * count(*) FILTER (WHERE decision = 'approve')
             / nullif(count(*) FILTER (WHERE decision <> 'no_response'), 0), 1)   AS acceptance_rate_pct,
       round(100.0 * count(*) FILTER (WHERE decision IN ('lighter', 'rest'))
             / nullif(count(*) FILTER (WHERE decision <> 'no_response'), 0), 1)   AS human_correction_rate_pct,
       round(100.0 * count(*) FILTER (WHERE decision = 'no_response') / count(*), 1) AS no_response_rate_pct,
       round(100.0 * count(*) FILTER (WHERE checker_rejections > 0) / count(*), 1)   AS runs_with_rejection_pct,
       round(avg(maker_attempts - 1), 2)                                          AS avg_retries,
       round(100.0 * count(*) FILTER (WHERE used_fallback) / count(*), 1)         AS fallback_rate_pct,
       round(avg(cost_usd), 6)                                                    AS avg_cost_per_run_usd,
       round(sum(cost_usd), 4)                                                    AS total_cost_usd
FROM v_kpi_runs runs
GROUP BY ROLLUP (data_source)
ORDER BY grouping(data_source), data_source;

\echo '== 2. Checker rejection rate (per LLM proposal, not per run)'
SELECT count(*)                                                    AS llm_proposals_checked,
       count(*) FILTER (WHERE NOT v.passed)                        AS rejected,
       round(100.0 * count(*) FILTER (WHERE NOT v.passed) / nullif(count(*), 0), 1) AS checker_rejection_rate_pct
FROM checker_verdicts v JOIN v_kpi_runs runs USING (run_id)
WHERE v.call_id IS NOT NULL;

\echo '== 3. Which guardrails fire'
SELECT viol->>'rule_id' AS rule_id, count(*) AS times_fired, count(DISTINCT v.run_id) AS runs
FROM checker_verdicts v JOIN v_kpi_runs runs USING (run_id), jsonb_array_elements(v.violations) viol
GROUP BY 1 ORDER BY 2 DESC;

\echo '== 4. Latency and tokens'
SELECT round(avg(agent_latency_ms))                                              AS avg_agent_latency_ms,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY agent_latency_ms)::numeric) AS p90_agent_latency_ms,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY human_response_s)::numeric) AS median_human_response_s,
       round(avg(input_tokens))                                                  AS avg_input_tokens,
       round(avg(output_tokens))                                                 AS avg_output_tokens
FROM v_kpi_runs runs;

\echo '== 5. Run log'
SELECT coalesce(scenario_id, 'live') AS scenario, decision, maker_attempts AS attempts, checker_rejections AS rejected,
       used_fallback AS fallback, round(agent_latency_ms) AS agent_ms, round(cost_usd, 6) AS cost_usd
FROM v_kpi_runs runs ORDER BY scenario;
