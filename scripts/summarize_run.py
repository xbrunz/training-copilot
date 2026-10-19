"""Summarise `n8n execute --rawOutput` from stdin: one line per node, plus the last node's output."""
import json
import sys

raw = sys.stdin.read()
start = raw.find("{")
end = raw.rfind("}")
if start < 0:
    sys.exit(raw[-2000:])
run = json.loads(raw[start:end + 1])
rd = run["data"]["resultData"]
print("status:", run.get("status"), "| last node:", rd.get("lastNodeExecuted"))
for node, runs in rd["runData"].items():
    r = runs[-1]
    items = sum(len(o or []) for o in (r.get("data") or {}).get("main", []))
    err = r.get("error")
    msg = (err.get("message", "") + " | " + str(err.get("description") or "")[:200]) if err else ""
    print(f"  {node:28s} {r.get('executionStatus', '?'):8s} items={items} {r.get('executionTime')}ms {msg}")
last = rd["runData"].get(rd.get("lastNodeExecuted"), [{}])[-1].get("data", {}).get("main", [[]])
if last and last[0] and "--quiet" not in sys.argv:
    print(json.dumps(last[0][0]["json"], indent=1)[:4000])
