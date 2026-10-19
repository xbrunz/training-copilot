-- Migration 02: pricing seed and logging details found while wiring the workflow.
SET search_path = copilot;

-- n8n retries HTTP calls internally and does not report how many retries it made,
-- so record "unknown" honestly instead of a misleading 0. Latency still shows retries.
ALTER TABLE llm_calls ALTER COLUMN http_retries DROP NOT NULL;
ALTER TABLE llm_calls ALTER COLUMN http_retries DROP DEFAULT;
COMMENT ON COLUMN llm_calls.http_retries IS 'NULL = not observable (n8n built-in retry)';

-- What the human saw and where
ALTER TABLE human_decisions ADD COLUMN telegram_message_id bigint;
ALTER TABLE planned_sessions ADD COLUMN focus text;

-- Price list, sourced from Anthropic's published pricing on this date
INSERT INTO model_pricing (model, valid_from, input_usd_per_mtok, output_usd_per_mtok, source_url)
VALUES ('claude-haiku-5-5', '2026-10-19', 0.10, 0.50, 'https://platform.claude.com/docs/en/about-claude/pricing')
ON CONFLICT DO NOTHING;
