-- Training Copilot: operational data model for agent runs.
-- One row per run in agent_runs; every LLM call, checker verdict and human
-- decision hangs off it, so any run can be replayed and audited end to end.
-- Cost is never stored: it is derived from tokens x model_pricing, so a
-- price change cannot silently rewrite history.

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA copilot;
SET search_path = copilot;

-- Price list per model, versioned by date (USD per million tokens)
CREATE TABLE model_pricing (
    model                text          NOT NULL,
    valid_from           date          NOT NULL,
    valid_to             date,
    input_usd_per_mtok   numeric(10,4) NOT NULL,
    output_usd_per_mtok  numeric(10,4) NOT NULL,
    source_url           text,
    PRIMARY KEY (model, valid_from)
);

CREATE TABLE agent_runs (
    run_id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    n8n_execution_id   text,
    workflow_version   text        NOT NULL,
    rules_version      text,
    trigger            text        NOT NULL CHECK (trigger IN ('schedule', 'manual')),
    data_source        text        NOT NULL CHECK (data_source IN ('live', 'scenario')),
    scenario_id        text,
    target_date        date        NOT NULL,
    status             text        NOT NULL DEFAULT 'running'
                       CHECK (status IN ('running', 'awaiting_human', 'completed', 'failed')),
    started_at         timestamptz NOT NULL DEFAULT now(),
    proposal_ready_at  timestamptz,           -- automated part done, human asked
    finished_at        timestamptz,
    context            jsonb,                 -- minimised features sent to the model, no identifiers
    maker_attempts     smallint    NOT NULL DEFAULT 0,
    used_fallback      boolean     NOT NULL DEFAULT false,
    final_proposal     jsonb,
    error              text
);
CREATE INDEX ON agent_runs (target_date);

-- Every maker call, including failed ones
CREATE TABLE llm_calls (
    call_id        bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id         uuid        NOT NULL REFERENCES agent_runs ON DELETE CASCADE,
    attempt        smallint    NOT NULL,      -- 1 = first proposal, 2..3 = retries after rejection
    model          text        NOT NULL,
    started_at     timestamptz NOT NULL,
    latency_ms     integer,
    http_retries   smallint    NOT NULL DEFAULT 0,
    input_tokens   integer,
    output_tokens  integer,
    stop_reason    text,
    proposal       jsonb,
    error          text,
    UNIQUE (run_id, attempt)
);

-- Deterministic guardrail results; call_id is null when the fallback is checked
CREATE TABLE checker_verdicts (
    verdict_id  bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id      uuid        NOT NULL REFERENCES agent_runs ON DELETE CASCADE,
    call_id     bigint      REFERENCES llm_calls,
    attempt     smallint    NOT NULL,
    passed      boolean     NOT NULL,
    violations  jsonb       NOT NULL DEFAULT '[]',  -- [{rule_id, message}]
    checked_at  timestamptz NOT NULL DEFAULT now()
);

-- Written once, when the human answers or the wait times out; never updated
CREATE TABLE human_decisions (
    run_id        uuid        PRIMARY KEY REFERENCES agent_runs ON DELETE CASCADE,
    channel       text        NOT NULL DEFAULT 'telegram',
    requested_at  timestamptz NOT NULL,
    decided_at    timestamptz,
    decision      text        NOT NULL CHECK (decision IN ('approve', 'lighter', 'rest', 'no_response'))
);

-- The action the human approved; only written after a decision
CREATE TABLE planned_sessions (
    run_id        uuid        PRIMARY KEY REFERENCES agent_runs ON DELETE CASCADE,
    session_date  date        NOT NULL,
    sport         text        NOT NULL,
    duration_min  smallint    NOT NULL,
    intensity     text        NOT NULL,
    location      text,
    origin        text        NOT NULL CHECK (origin IN ('agent', 'fallback', 'human_lighter', 'human_rest')),
    pushed_at     timestamptz,                -- day 2: pushed to intervals.icu calendar
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- Cost per LLM call, priced at the rate valid on the day of the call
CREATE VIEW v_llm_call_cost AS
SELECT c.*,
       (c.input_tokens  * p.input_usd_per_mtok
      + c.output_tokens * p.output_usd_per_mtok) / 1e6 AS cost_usd
FROM llm_calls c
LEFT JOIN model_pricing p
       ON p.model = c.model
      AND c.started_at::date >= p.valid_from
      AND (p.valid_to IS NULL OR c.started_at::date < p.valid_to);

-- One row per run: the basis for every KPI
CREATE VIEW v_run_summary AS
SELECT r.run_id, r.target_date, r.trigger, r.data_source, r.scenario_id, r.status,
       r.maker_attempts, r.used_fallback,
       (SELECT count(*) FROM checker_verdicts v WHERE v.run_id = r.run_id AND NOT v.passed) AS checker_rejections,
       h.decision,
       extract(epoch FROM r.proposal_ready_at - r.started_at) * 1000 AS agent_latency_ms,
       extract(epoch FROM h.decided_at - h.requested_at)            AS human_response_s,
       coalesce(sum(c.input_tokens), 0)  AS input_tokens,
       coalesce(sum(c.output_tokens), 0) AS output_tokens,
       coalesce(sum(c.cost_usd), 0)      AS cost_usd
FROM agent_runs r
LEFT JOIN human_decisions h  ON h.run_id = r.run_id
LEFT JOIN v_llm_call_cost c  ON c.run_id = r.run_id
GROUP BY r.run_id, h.decision, h.decided_at, h.requested_at;

-- Least privilege: the writer can append and update run state, never delete or change prices
GRANT USAGE ON SCHEMA copilot TO copilot_writer, copilot_reader;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA copilot TO copilot_writer;
REVOKE INSERT ON model_pricing FROM copilot_writer;
GRANT UPDATE ON agent_runs, planned_sessions TO copilot_writer;  -- human_decisions is insert-only
GRANT SELECT ON ALL TABLES IN SCHEMA copilot TO copilot_reader;  -- includes views
ALTER ROLE copilot_writer SET search_path = copilot;
ALTER ROLE copilot_reader SET search_path = copilot;
