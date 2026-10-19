"""Assemble the n8n workflow JSON files from small, testable pieces.

Code-node logic lives in workflows/code/*.js (unit-tested with Node), and this
script embeds it into the workflow JSON. Output contains credential IDs and
names only, never secrets.

Usage: python3 scripts/build_workflows.py   then   ./scripts/n8n_import.sh
"""
import json
import pathlib
import re
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
CODE = ROOT / "workflows" / "code"
MAIN_ID = "TrainCopilotMain"
RUNNER_ID = "TrainCopilotTest"
VERSION = "v0.4-hitl-logging"

CRED_INTERVALS = {"httpBasicAuth": {"id": "intervalsApiKey1", "name": "intervals.icu API key"}}
CRED_ANTHROPIC = {"httpHeaderAuth": {"id": "anthropicApiKey1", "name": "Anthropic API key"}}
RETRY = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000}


def js(*names):
    """Concatenate module files for a Code node, dropping their Node-only export lines."""
    src = "\n".join((CODE / n).read_text() for n in names)
    return re.sub(r"^if \(typeof module !== 'undefined'\).*\n", "", src, flags=re.M)


class Flow:
    def __init__(self):
        self.nodes, self.connections = [], {}

    def node(self, name, type_, version, pos, params=None, **extra):
        self.nodes.append({"id": str(uuid.uuid5(uuid.NAMESPACE_URL, name)), "name": name,
                           "type": f"n8n-nodes-base.{type_}", "typeVersion": version,
                           "position": list(pos), "parameters": params or {}, **extra})
        return name

    def link(self, src, dst, out=0):
        outs = self.connections.setdefault(src, {"main": []})["main"]
        while len(outs) <= out:
            outs.append([])
        outs[out].append({"node": dst, "type": "main", "index": 0})

    def sticky(self, text, pos, size, color=7):
        self.node(f"Note: {text.splitlines()[0]}", "stickyNote", 1, pos,
                  {"content": text, "width": size[0], "height": size[1], "color": color})


def code(source):
    return {"jsCode": source}


def http(url, query, cred=None):
    p = {"url": url, "sendQuery": True,
         "queryParameters": {"parameters": [{"name": k, "value": v} for k, v in query.items()]},
         "options": {"timeout": 15000}}
    if cred:
        p.update(authentication="genericCredentialType", genericAuthType="httpBasicAuth")
    return p


RUN_CONFIG = f"""// Normalise the three entry points into one run config
const input = $input.first().json;
const scenarioId = input.scenario_id ? String(input.scenario_id) : null;
// Guardrail on input: scenario IDs become file paths, so allow a strict pattern only
if (scenarioId && !/^s[0-9]{{2}}_[a-z0-9_]{{1,40}}$/.test(scenarioId)) {{
  throw new Error(`Invalid scenario_id: ${{scenarioId}}`);
}}
// Only two config files exist; anything else is refused
const guardrailsFile = input.guardrails_file || 'guardrails.json';
if (!['guardrails.json', 'guardrails.test.json'].includes(guardrailsFile)) {{
  throw new Error(`Invalid guardrails_file: ${{guardrailsFile}}`);
}}
const lisbon = $now.setZone('Europe/Lisbon');
return [{{ json: {{
  workflow_version: '{VERSION}',
  n8n_execution_id: $execution.id,
  run_started_at: new Date().toISOString(),
  trigger: $('Every day 21:00').isExecuted ? 'schedule' : 'manual',
  mode: scenarioId ? 'scenario' : 'live',
  scenario_id: scenarioId,
  guardrails_file: guardrailsFile,
  today: lisbon.toISODate(),
  target_date: lisbon.plus({{ days: 1 }}).toISODate(),
}} }}];
"""

SHAPE_LIVE = """// intervals.icu returns arrays, which n8n splits into items: gather them back
const cfg = $('Run config').first().json;
const rows = (node) => $(node).all().map((i) => i.json).filter((j) => j && j.id);
return [{ json: {
  ...cfg,
  wellness: rows('intervals.icu wellness'),
  activities: rows('intervals.icu activities'),
  weather: $('Open-Meteo forecast').first().json,
} }];
"""

SHAPE_SCENARIO = """// A scenario file replaces the three API responses; everything downstream is identical
const cfg = $('Run config').first().json;
const s = $input.first().json.data;
return [{ json: {
  ...cfg,
  target_date: s.target_date,
  wellness: s.wellness,
  activities: s.activities,
  weather: s.weather,
} }];
"""

BUILD_WRAPPER = """
// --- n8n wrapper
const raw = $('Shape live data').isExecuted
  ? $('Shape live data').first().json
  : $('Shape scenario data').first().json;
const plan = $input.first().json.data;
const context = buildContext({
  targetDate: raw.target_date, source: raw.mode, scenarioId: raw.scenario_id,
  wellness: raw.wellness, activities: raw.activities, weather: raw.weather, plan,
});
const run = {
  workflow_version: raw.workflow_version, n8n_execution_id: raw.n8n_execution_id,
  run_started_at: raw.run_started_at, trigger: raw.trigger, data_source: raw.mode,
  scenario_id: raw.scenario_id, target_date: raw.target_date, guardrails_file: raw.guardrails_file,
};
return [{ json: { run, context } }];
"""


START_LOOP = """// Loop state travels in the item: run, context, guardrails, and every attempt so far
const g = $input.first().json.data;
const { run, context } = $('Build daily context').first().json;
return [{ json: { run, context, guardrails: g, rules_version: g.version, attempts: [] } }];
"""

PREPARE = """
// --- n8n wrapper: one request per attempt; earlier rejections are quoted in the prompt
const s = $input.first().json;
const attempt = s.attempts.length + 1;
return [{ json: {
  ...s,
  attempt,
  call_started_at: new Date().toISOString(),
  call_started_ms: Date.now(),
  request_body: buildMakerRequest(s.context, s.attempts),
} }];
"""

PARSE = """
// --- n8n wrapper: recover loop state from the request node, record this call
const s = $('Prepare maker request').last().json;
const parsed = parseMakerResponse($input.first().json);
const call = {
  attempt: s.attempt, model: parsed.model, started_at: s.call_started_at,
  latency_ms: Date.now() - s.call_started_ms, stop_reason: parsed.stop_reason,
  input_tokens: parsed.input_tokens, output_tokens: parsed.output_tokens, error: parsed.error,
};
const { request_body, call_started_ms, call_started_at, ...state } = s;
return [{ json: { ...state, proposal: parsed.proposal, call } }];
"""

CHECK = """
// --- n8n wrapper: deterministic verdict, appended to the attempt history
const s = $input.first().json;
const verdict = checkProposal(s.proposal, s.context, s.guardrails);
const attempts = [...s.attempts, { attempt: s.attempt, proposal: s.proposal, verdict, call: s.call }];
const maxAttempts = 1 + Math.min(Number(s.guardrails.max_maker_retries) || 0, 4); // hard cap
return [{ json: { ...s, attempts, verdict, retry_allowed: !verdict.passed && attempts.length < maxAttempts } }];
"""

MAKER_FAILED = """// The API call failed after its HTTP retries: no point re-asking the model
const s = $('Prepare maker request').last().json;
const err = $input.first().json.error || {};
const call = { attempt: s.attempt, model: 'claude-haiku-5-5', started_at: s.call_started_at,
  latency_ms: Date.now() - s.call_started_ms, stop_reason: null, input_tokens: null, output_tokens: null,
  error: `HTTP error: ${err.message || JSON.stringify(err).slice(0, 200)}` };
const { request_body, call_started_ms, call_started_at, ...state } = s;
const verdict = { passed: false, violations: [{ rule_id: 'S0_api', message: call.error }], not_configured: [] };
return [{ json: { ...state, attempts: [...s.attempts, { attempt: s.attempt, proposal: null, verdict, call }] } }];
"""

ACCEPT = """// Checker passed: the agent's proposal goes to the human
const s = $input.first().json;
return [{ json: { run: s.run, context: s.context, rules_version: s.rules_version, attempts: s.attempts,
  final: { origin: 'agent', proposal: s.proposal, verdict: s.verdict } } }];
"""

FALLBACK = """
// --- n8n wrapper: deterministic safe session, re-checked so the fallback is provably within the rules
const s = $input.first().json;
const proposal = safeFallback(s.context, s.guardrails);
const verdict = checkProposal(proposal, s.context, s.guardrails);
return [{ json: { run: s.run, context: s.context, rules_version: s.rules_version, attempts: s.attempts,
  final: { origin: 'fallback', proposal, verdict } } }];
"""


CRED_PG = {"postgres": {"id": "pgCopilotWriter1", "name": "Postgres copilot_writer"}}
CRED_TG = {"telegramApi": {"id": "telegramBot00001", "name": "Telegram bot"}}

# One atomic statement per log write: the run, every LLM call, every verdict
SQL_LOG_PROPOSAL = """WITH p AS (SELECT $1::jsonb AS j),
run AS (
  INSERT INTO agent_runs (n8n_execution_id, workflow_version, rules_version, trigger, data_source, scenario_id,
                          target_date, status, started_at, proposal_ready_at, context, maker_attempts,
                          used_fallback, final_proposal)
  SELECT j#>>'{run,n8n_execution_id}', j#>>'{run,workflow_version}', j->>'rules_version', j#>>'{run,trigger}',
         j#>>'{run,data_source}', j#>>'{run,scenario_id}', (j#>>'{run,target_date}')::date, 'awaiting_human',
         (j#>>'{run,run_started_at}')::timestamptz, now(), j->'context',
         jsonb_array_length(j->'attempts')::smallint, j#>>'{final,origin}' = 'fallback', j#>'{final,proposal}'
  FROM p
  RETURNING run_id
),
attempts AS (SELECT a FROM p, jsonb_array_elements(p.j->'attempts') a),
calls AS (
  INSERT INTO llm_calls (run_id, attempt, model, started_at, latency_ms, input_tokens, output_tokens,
                         stop_reason, proposal, error)
  SELECT run.run_id, (a->>'attempt')::smallint, a#>>'{call,model}', (a#>>'{call,started_at}')::timestamptz,
         (a#>>'{call,latency_ms}')::int, (a#>>'{call,input_tokens}')::int, (a#>>'{call,output_tokens}')::int,
         a#>>'{call,stop_reason}', NULLIF(a->'proposal', 'null'::jsonb), a#>>'{call,error}'
  FROM run, attempts
  RETURNING call_id, run_id, attempt
),
verdicts AS (
  INSERT INTO checker_verdicts (run_id, call_id, attempt, passed, violations)
  SELECT c.run_id, c.call_id, c.attempt, (a#>>'{verdict,passed}')::boolean, a#>'{verdict,violations}'
  FROM calls c JOIN attempts ON (a->>'attempt')::smallint = c.attempt
  UNION ALL
  SELECT run.run_id, NULL, (jsonb_array_length(j->'attempts') + 1)::smallint,
         (j#>>'{final,verdict,passed}')::boolean, j#>'{final,verdict,violations}'
  FROM run, p WHERE j#>>'{final,origin}' = 'fallback'
  RETURNING 1
)
SELECT run_id, (SELECT count(*) FROM calls) AS calls_logged, (SELECT count(*) FROM verdicts) AS verdicts_logged
FROM run;"""

SQL_LOG_DECISION = """WITH p AS (SELECT $1::jsonb AS j),
d AS (
  INSERT INTO human_decisions (run_id, channel, requested_at, decided_at, decision, telegram_message_id)
  SELECT (j->>'run_id')::uuid, 'telegram', (j->>'requested_at')::timestamptz,
         CASE WHEN j->>'decision' = 'no_response' THEN NULL ELSE now() END,
         j->>'decision', (j->>'telegram_message_id')::bigint
  FROM p
  RETURNING run_id
),
s AS (
  INSERT INTO planned_sessions (run_id, session_date, sport, duration_min, intensity, location, focus, origin)
  SELECT (j->>'run_id')::uuid, (j->>'target_date')::date, j#>>'{session,sport}',
         (j#>>'{session,duration_min}')::smallint, j#>>'{session,intensity}', j#>>'{session,location}',
         j#>>'{session,focus}', j->>'origin'
  FROM p WHERE jsonb_typeof(j->'session') = 'object'
  RETURNING run_id
),
r AS (
  UPDATE agent_runs SET status = 'completed', finished_at = now()
  WHERE run_id = (SELECT (j->>'run_id')::uuid FROM p)
  RETURNING run_id
)
SELECT (SELECT count(*) FROM d) AS decisions, (SELECT count(*) FROM s) AS sessions,
       (SELECT count(*) FROM r) AS runs_closed;"""

BUILD_APPROVAL = """
// --- n8n wrapper: message text + three signed resume-URL buttons
const s = $('Proposal ready').first().json;
const settings = $input.first().json.data;
return [{ json: {
  run_id: $('Log proposal').first().json.run_id,
  chat_id: String(settings.telegram_chat_id),
  timeout_min: Number(settings.approval_timeout_min) || 180,
  requested_at: new Date().toISOString(),
  text: formatApproval(s),
  buttons: approvalButtons($execution.resumeUrl),
} }];
"""

APPLY_DECISION = """
// --- n8n wrapper: resumed by a button (query.decision) or by the timeout (no query)
const s = $('Proposal ready').first().json;
const req = $('Build approval message').first().json;
const sent = $('Ask for approval').first().json;
const query = $input.first().json.query;
const result = applyDecision(query ? query.decision : null, s.final.proposal);
const labels = { approve: '✅ Approved', lighter: '🪶 Lighter', rest: '😴 Rest', no_response: '⌛ No answer' };
const outcome = result.session
  ? `${labels[result.decision]} → <b>${result.session.sport === 'rest' ? 'Rest' : `${result.session.sport} · ${result.session.duration_min} min · ${result.session.intensity} · ${result.session.location}`}</b>`
  : `${labels.no_response} within ${req.timeout_min} min: nothing scheduled`;
return [{ json: {
  run_id: req.run_id, target_date: s.run.target_date, requested_at: req.requested_at,
  decision: result.decision, session: result.session, origin: result.origin || s.final.origin,
  telegram_message_id: (sent.result || sent).message_id, chat_id: req.chat_id,
  resumed_by_button: !!query,
  confirmation: `${req.text}\\n\\n<b>Decision:</b> ${outcome}`,
} }];
"""

RESPONSE_PAGE = ("=<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                 "<body style='font-family:system-ui;padding:2rem'><h2>{{ $('Apply decision').first().json.decision"
                 " === 'approve' ? '✅ Approved' : $('Apply decision').first().json.decision === 'lighter'"
                 " ? '🪶 Lighter session' : '😴 Rest day' }}</h2><p>Recorded. You can close this tab.</p>")


def main_workflow():
    f = Flow()
    f.sticky("## 1 · Collect\nRecovery and load (intervals.icu), weather (Open-Meteo), weekly plan. "
             "Scenarios replace the API calls for testing; everything after this is identical.",
             (-20, -260), (1720, 760), color=5)
    f.node("Every day 21:00", "scheduleTrigger", 1.2, (40, -100),
           {"rule": {"interval": [{"field": "cronExpression", "expression": "0 21 * * *"}]}},
           disabled=True, notes="Disabled until the full pipeline is built")
    f.node("Run manually", "manualTrigger", 1, (40, 80))
    f.node("Manual run settings", "set", 3.4, (240, 80), {
        "assignments": {"assignments": [{"id": "scn", "name": "scenario_id", "type": "string",
                                         "value": "s01_good_recovery_intervals"}]},
        "options": {}}, notes="Empty scenario_id = live data")
    f.node("Called by test runner", "executeWorkflowTrigger", 1.1, (40, 260),
           {"workflowInputs": {"values": [{"name": "scenario_id", "type": "string"},
                                            {"name": "guardrails_file", "type": "string"}]}})
    f.node("Run config", "code", 2, (460, 80), code(RUN_CONFIG))
    f.node("Live data?", "if", 2.2, (660, 80), {
        "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                       "conditions": [{"id": "live", "leftValue": "={{ $json.mode }}", "rightValue": "live",
                                       "operator": {"type": "string", "operation": "equals"}}],
                       "combinator": "and"}, "options": {}})
    cfg = "$('Run config').first().json"
    f.node("intervals.icu wellness", "httpRequest", 4.2, (880, -60),
           http("https://intervals.icu/api/v1/athlete/0/wellness",
                {"oldest": "={{ DateTime.fromISO($json.today).minus({ days: 7 }).toISODate() }}",
                 "newest": "={{ $json.today }}"}, cred=True),
           credentials=CRED_INTERVALS, alwaysOutputData=True, **RETRY,
           notes="athlete/0 = the key's owner, so no athlete ID is stored in the workflow")
    f.node("intervals.icu activities", "httpRequest", 4.2, (1100, -60),
           http("https://intervals.icu/api/v1/athlete/0/activities",
                {"oldest": f"={{{{ DateTime.fromISO({cfg}.today).minus({{ days: 13 }}).toISODate() }}}}",
                 "newest": f"={{{{ {cfg}.today }}}}"}, cred=True),
           credentials=CRED_INTERVALS, alwaysOutputData=True, executeOnce=True, **RETRY)
    f.node("Open-Meteo forecast", "httpRequest", 4.2, (1320, -60),
           http("https://api.open-meteo.com/v1/forecast",
                {"latitude": "38.72", "longitude": "-9.14", "timezone": "Europe/Lisbon",
                 "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum,"
                          "precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max",
                 "start_date": f"={{{{ {cfg}.target_date }}}}", "end_date": f"={{{{ {cfg}.target_date }}}}"}),
           executeOnce=True, **RETRY, notes="Lisbon. Free, no key.")
    f.node("Shape live data", "code", 2, (1540, -60), code(SHAPE_LIVE))
    f.node("Read scenario file", "readWriteFile", 1, (880, 240),
           {"operation": "read", "fileSelector": "=/data/sample/scenarios/{{ $json.scenario_id }}.json", "options": {}})
    f.node("Parse scenario", "extractFromFile", 1, (1100, 240), {"operation": "fromJson", "options": {}})
    f.node("Shape scenario data", "code", 2, (1320, 240), code(SHAPE_SCENARIO))
    f.node("Read weekly plan", "readWriteFile", 1, (1760, 80),
           {"operation": "read", "fileSelector": "/data/plan/weekly_plan.json", "options": {}})
    f.node("Parse weekly plan", "extractFromFile", 1, (1980, 80), {"operation": "fromJson", "options": {}})
    f.node("Build daily context", "code", 2, (2200, 80), code(js("build_context.js") + BUILD_WRAPPER),
           notes="Data minimisation: only numbers and categories go to the agent")

    f.link("Every day 21:00", "Run config")
    f.link("Run manually", "Manual run settings")
    f.link("Manual run settings", "Run config")
    f.link("Called by test runner", "Run config")
    f.link("Run config", "Live data?")
    f.link("Live data?", "intervals.icu wellness", 0)
    f.link("Live data?", "Read scenario file", 1)
    f.link("intervals.icu wellness", "intervals.icu activities")
    f.link("intervals.icu activities", "Open-Meteo forecast")
    f.link("Open-Meteo forecast", "Shape live data")
    f.link("Shape live data", "Read weekly plan")
    f.link("Read scenario file", "Parse scenario")
    f.link("Parse scenario", "Shape scenario data")
    f.link("Shape scenario data", "Read weekly plan")
    f.link("Read weekly plan", "Parse weekly plan")
    f.link("Parse weekly plan", "Build daily context")

    # --- 2 · Maker / checker loop
    f.sticky("## 2 · Maker / checker\nClaude Haiku proposes (strict JSON schema). Deterministic rules check. "
             "Rejected: retry with the reasons (max from config). Still rejected or API down: safe fallback.",
             (2400, -260), (2380, 760), color=4)
    f.node("Read guardrails", "readWriteFile", 1, (2460, 80),
           {"operation": "read", "fileSelector": "=/config/{{ $('Run config').first().json.guardrails_file }}", "options": {}},
           notes="Thresholds set by the athlete; versioned")
    f.node("Parse guardrails", "extractFromFile", 1, (2660, 80), {"operation": "fromJson", "options": {}})
    f.node("Start maker loop", "code", 2, (2860, 80), code(START_LOOP))
    f.node("Prepare maker request", "code", 2, (3060, 80), code(js("maker.js") + PREPARE))
    f.node("Maker · Claude Haiku", "httpRequest", 4.2, (3260, 80), {
        "method": "POST", "url": "https://api.anthropic.com/v1/messages",
        "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
        "sendHeaders": True,
        "headerParameters": {"parameters": [{"name": "anthropic-version", "value": "2023-06-01"}]},
        "sendBody": True, "specifyBody": "json", "jsonBody": "={{ JSON.stringify($json.request_body) }}",
        "options": {"timeout": 60000}},
        credentials=CRED_ANTHROPIC, onError="continueErrorOutput",
        retryOnFail=True, maxTries=3, waitBetweenTries=3000,
        notes="Retries 429/5xx/timeouts 3x; then error output -> fallback")
    f.node("Parse proposal", "code", 2, (3480, 0), code(js("maker.js") + PARSE))
    f.node("Checker · guardrails", "code", 2, (3700, 0), code(js("checker.js") + CHECK),
           notes="Deterministic. No LLM.")
    f.node("Passed checker?", "if", 2.2, (3920, 0), {
        "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                       "conditions": [{"id": "ok", "leftValue": "={{ $json.verdict.passed }}", "rightValue": True,
                                       "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                       "combinator": "and"}, "options": {}})
    f.node("Retry allowed?", "if", 2.2, (4140, 160), {
        "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                       "conditions": [{"id": "retry", "leftValue": "={{ $json.retry_allowed }}", "rightValue": True,
                                       "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                       "combinator": "and"}, "options": {}})
    f.node("Maker call failed", "code", 2, (3480, 260), code(MAKER_FAILED))
    f.node("Accept agent proposal", "code", 2, (4360, -60), code(ACCEPT))
    f.node("Safe fallback", "code", 2, (4360, 260), code(js("checker.js") + FALLBACK),
           notes="Rule-based easy session or rest; never an LLM output")
    f.node("Proposal ready", "noOp", 1, (4600, 80))

    f.link("Build daily context", "Read guardrails")
    f.link("Read guardrails", "Parse guardrails")
    f.link("Parse guardrails", "Start maker loop")
    f.link("Start maker loop", "Prepare maker request")
    f.link("Prepare maker request", "Maker · Claude Haiku")
    f.link("Maker · Claude Haiku", "Parse proposal", 0)
    f.link("Maker · Claude Haiku", "Maker call failed", 1)
    f.link("Parse proposal", "Checker · guardrails")
    f.link("Checker · guardrails", "Passed checker?")
    f.link("Passed checker?", "Accept agent proposal", 0)
    f.link("Passed checker?", "Retry allowed?", 1)
    f.link("Retry allowed?", "Prepare maker request", 0)
    f.link("Retry allowed?", "Safe fallback", 1)
    f.link("Maker call failed", "Safe fallback")
    f.link("Accept agent proposal", "Proposal ready")
    f.link("Safe fallback", "Proposal ready")

    # --- 3 · Human approval + audit log
    f.sticky("## 3 · Human in the loop + audit log\nThe run, every LLM call and verdict are logged before asking. "
             "Telegram buttons resume this execution via its signed URL. Nothing is scheduled without an answer.",
             (4780, -260), (2620, 760), color=6)
    f.node("Log proposal", "postgres", 2.5, (4840, 80), {
        "operation": "executeQuery", "query": SQL_LOG_PROPOSAL,
        "options": {"queryReplacement": "={{ [JSON.stringify($json)] }}"}},
        credentials=CRED_PG, notes="Atomic: run + LLM calls + verdicts")
    f.node("Read settings", "readWriteFile", 1, (5040, 80),
           {"operation": "read", "fileSelector": "/data/private/settings.json", "options": {}},
           notes="Chat ID lives outside the repo")
    f.node("Parse settings", "extractFromFile", 1, (5240, 80), {"operation": "fromJson", "options": {}})
    f.node("Build approval message", "code", 2, (5440, 80), code(js("approval.js") + BUILD_APPROVAL))
    btn = lambda i: {"text": f"={{{{ $json.buttons[{i}].text }}}}", "additionalFields": {"url": f"={{{{ $json.buttons[{i}].url }}}}"}}
    f.node("Ask for approval", "telegram", 1.2, (5640, 80), {
        "chatId": "={{ $json.chat_id }}", "text": "={{ $json.text }}",
        "replyMarkup": "inlineKeyboard",
        "inlineKeyboard": {"rows": [{"row": {"buttons": [btn(0), btn(1), btn(2)]}}]},
        "additionalFields": {"parse_mode": "HTML", "appendAttribution": False}},
        credentials=CRED_TG, **RETRY)
    f.node("Wait for decision", "wait", 1.1, (5840, 80), {
        "resume": "webhook", "httpMethod": "GET", "responseMode": "responseNode",
        "limitWaitTime": True, "limitType": "afterTimeInterval",
        "resumeAmount": "={{ $('Build approval message').first().json.timeout_min }}", "resumeUnit": "minutes",
        "options": {}}, notes="Resumes on a button tap, or after the timeout")
    f.node("Apply decision", "code", 2, (6040, 80), code(js("approval.js") + APPLY_DECISION))
    f.node("Log decision", "postgres", 2.5, (6240, 80), {
        "operation": "executeQuery", "query": SQL_LOG_DECISION,
        "options": {"queryReplacement": "={{ [JSON.stringify($json)] }}"}},
        credentials=CRED_PG, notes="Decision is insert-only")
    f.node("Answered by button?", "if", 2.2, (6440, 80), {
        "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                       "conditions": [{"id": "btn", "leftValue": "={{ $('Apply decision').first().json.resumed_by_button }}",
                                       "rightValue": True,
                                       "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                       "combinator": "and"}, "options": {}})
    f.node("Show confirmation page", "respondToWebhook", 1.1, (6660, -20), {
        "respondWith": "text", "responseBody": RESPONSE_PAGE,
        "options": {"responseHeaders": {"entries": [{"name": "content-type", "value": "text/html; charset=utf-8"}]}}})
    f.node("Update Telegram message", "telegram", 1.2, (6880, 80), {
        "resource": "message", "operation": "editMessageText", "messageType": "message",
        "chatId": "={{ $('Apply decision').first().json.chat_id }}",
        "messageId": "={{ $('Apply decision').first().json.telegram_message_id }}",
        "text": "={{ $('Apply decision').first().json.confirmation }}",
        "additionalFields": {"parse_mode": "HTML"}},
        credentials=CRED_TG, **RETRY, notes="Shows the decision and removes the buttons")

    f.link("Proposal ready", "Log proposal")
    f.link("Log proposal", "Read settings")
    f.link("Read settings", "Parse settings")
    f.link("Parse settings", "Build approval message")
    f.link("Build approval message", "Ask for approval")
    f.link("Ask for approval", "Wait for decision")
    f.link("Wait for decision", "Apply decision")
    f.link("Apply decision", "Log decision")
    f.link("Log decision", "Answered by button?")
    f.link("Answered by button?", "Show confirmation page", 0)
    f.link("Answered by button?", "Update Telegram message", 1)
    f.link("Show confirmation page", "Update Telegram message")
    return {"id": MAIN_ID, "name": "Training Copilot", "active": False, "nodes": f.nodes,
            "connections": f.connections, "pinData": {},
            "settings": {"executionOrder": "v1", "timezone": "Europe/Lisbon",
                         "callerPolicy": "workflowsFromSameOwner"}}


def runner_workflow():
    scenarios = sorted(p.stem for p in (ROOT / "data" / "sample" / "scenarios").glob("s*.json"))
    f = Flow()
    f.node("Start test batch", "webhook", 2, (0, 0), {
        "httpMethod": "GET", "path": "training-copilot-test-batch", "authentication": "headerAuth",
        "responseMode": "lastNode", "options": {}},
        webhookId="training-copilot-test-batch",
        credentials={"httpHeaderAuth": {"id": "testRunnerToken1", "name": "Test runner token"}},
        notes="127.0.0.1 only, X-Test-Token header required. See scripts/run_batch.sh")
    f.node("Scenario list", "code", 2, (220, 0), code(
        "// ?scenarios=all | live | comma-separated IDs; ?guardrails=guardrails.json | guardrails.test.json\n"
        f"const all = {json.dumps(scenarios)};\n"
        "const q = $input.first().json.query || {};\n"
        "const want = String(q.scenarios || 'all');\n"
        "const ids = want === 'all' ? [...all, ''] : want.split(',').map((s) => (s === 'live' ? '' : s.trim()));\n"
        "const unknown = ids.filter((id) => id && !all.includes(id));\n"
        "if (unknown.length) throw new Error(`Unknown scenarios: ${unknown.join(', ')}`);\n"
        "const guardrails_file = q.guardrails || 'guardrails.json';\n"
        "return ids.map((scenario_id) => ({ json: { scenario_id, guardrails_file } }));"))
    f.node("Run Training Copilot", "executeWorkflow", 1.2, (440, 0), {
        "workflowId": {"__rl": True, "value": MAIN_ID, "mode": "id"},
        "workflowInputs": {"mappingMode": "defineBelow", "value": {"scenario_id": "={{ $json.scenario_id }}",
                                                         "guardrails_file": "={{ $json.guardrails_file }}"},
                           "matchingColumns": [], "attemptToConvertTypes": False, "convertFieldsToString": True,
                           "schema": [{"id": k, "displayName": k, "required": False, "defaultMatch": False,
                                       "display": True, "canBeUsedToMatch": True, "type": "string"}
                                      for k in ("scenario_id", "guardrails_file")]},
        "mode": "each", "options": {"waitForSubWorkflow": False}},
        notes="Fire and forget: each run waits for its own Telegram answer")
    f.node("Batch started", "code", 2, (660, 0), code(
        "return [{ json: { started: $input.all().length, scenarios: $('Scenario list').all().map((i) => i.json.scenario_id || 'live') } }];"))
    f.link("Start test batch", "Scenario list")
    f.link("Scenario list", "Run Training Copilot")
    f.link("Run Training Copilot", "Batch started")
    return {"id": RUNNER_ID, "name": "Training Copilot · test runner", "active": False, "nodes": f.nodes,
            "connections": f.connections, "pinData": {},
            "settings": {"executionOrder": "v1", "timezone": "Europe/Lisbon"}}


if __name__ == "__main__":
    out = ROOT / "workflows"
    for name, wf in [("training-copilot.json", main_workflow()), ("test-runner.json", runner_workflow())]:
        (out / name).write_text(json.dumps(wf, indent=2) + "\n")
        print(f"wrote workflows/{name}: {len(wf['nodes'])} nodes")
