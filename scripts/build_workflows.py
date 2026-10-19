"""Assemble the n8n workflow JSON files from small, testable pieces.

Code-node logic lives in workflows/code/*.js (unit-tested with Node), and this
script embeds it into the workflow JSON. Output contains credential IDs and
names only, never secrets.

Usage: python3 scripts/build_workflows.py   then   ./scripts/n8n_import.sh
"""
import json
import pathlib
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
CODE = ROOT / "workflows" / "code"
MAIN_ID = "TrainCopilotMain"
RUNNER_ID = "TrainCopilotTest"
VERSION = "v0.2-collect"

CRED_INTERVALS = {"httpBasicAuth": {"id": "intervalsApiKey1", "name": "intervals.icu API key"}}
RETRY = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000}


def js(name):
    src = (CODE / name).read_text()
    return src.replace("if (typeof module !== 'undefined') module.exports = { buildContext };\n", "")


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
const lisbon = $now.setZone('Europe/Lisbon');
return [{{ json: {{
  workflow_version: '{VERSION}',
  n8n_execution_id: $execution.id,
  run_started_at: new Date().toISOString(),
  trigger: $('Every day 21:00').isExecuted ? 'schedule' : 'manual',
  mode: scenarioId ? 'scenario' : 'live',
  scenario_id: scenarioId,
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
  scenario_id: raw.scenario_id, target_date: raw.target_date,
};
return [{ json: { run, context } }];
"""


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
           {"workflowInputs": {"values": [{"name": "scenario_id", "type": "string"}]}})
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
    return {"id": MAIN_ID, "name": "Training Copilot", "active": False, "nodes": f.nodes,
            "connections": f.connections, "pinData": {},
            "settings": {"executionOrder": "v1", "timezone": "Europe/Lisbon",
                         "callerPolicy": "workflowsFromSameOwner"}}


def runner_workflow():
    scenarios = sorted(p.stem for p in (ROOT / "data" / "sample" / "scenarios").glob("s*.json"))
    f = Flow()
    f.node("Run test batch", "manualTrigger", 1, (0, 0))
    f.node("Scenario list", "code", 2, (220, 0), code(
        "// Every sample scenario, plus one live run (empty scenario_id)\n"
        f"const ids = {json.dumps(scenarios)};\n"
        "return [...ids, ''].map((scenario_id) => ({ json: { scenario_id } }));"))
    f.node("Run Training Copilot", "executeWorkflow", 1.2, (440, 0), {
        "workflowId": {"__rl": True, "value": MAIN_ID, "mode": "id"},
        "workflowInputs": {"mappingMode": "defineBelow", "value": {"scenario_id": "={{ $json.scenario_id }}"},
                           "matchingColumns": [], "attemptToConvertTypes": False, "convertFieldsToString": True,
                           "schema": [{"id": "scenario_id", "displayName": "scenario_id", "required": False,
                                       "defaultMatch": False, "display": True, "canBeUsedToMatch": True,
                                       "type": "string"}]},
        "mode": "each", "options": {"waitForSubWorkflow": True}})
    f.link("Run test batch", "Scenario list")
    f.link("Scenario list", "Run Training Copilot")
    return {"id": RUNNER_ID, "name": "Training Copilot · test runner", "active": False, "nodes": f.nodes,
            "connections": f.connections, "pinData": {},
            "settings": {"executionOrder": "v1", "timezone": "Europe/Lisbon"}}


if __name__ == "__main__":
    out = ROOT / "workflows"
    for name, wf in [("training-copilot.json", main_workflow()), ("test-runner.json", runner_workflow())]:
        (out / name).write_text(json.dumps(wf, indent=2) + "\n")
        print(f"wrote workflows/{name}: {len(wf['nodes'])} nodes")
