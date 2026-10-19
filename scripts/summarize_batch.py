"""Summarise a test-runner execution from stdin: one line per run, then each rejected attempt."""
import json
import sys

raw = sys.stdin.read()
run = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
rd = run["data"]["resultData"]
print("runner status:", run.get("status"), rd.get("error", {}).get("message", ""))
items = rd["runData"]["Run Training Copilot"][-1].get("data", {}).get("main", [[]])[0]
tot_in = tot_out = 0
for it in items:
    j = it["json"]
    f, p = j["final"], j["final"]["proposal"]
    calls = [a["call"] for a in j["attempts"]]
    tin = sum(c["input_tokens"] or 0 for c in calls); tout = sum(c["output_tokens"] or 0 for c in calls)
    tot_in += tin; tot_out += tout
    planned = j["context"]["planned"]
    print(f'{(j["run"]["scenario_id"] or "LIVE"):28s} plan {planned["sport"]}/{planned["intensity"]}/{planned["duration_min"]} '
          f'-> {f["origin"]:8s} {p["sport"]}/{p["intensity"]}/{p["duration_min"]}/{p["location"]} '
          f'attempts={len(calls)} tokens={tin}+{tout} latency={sum(c["latency_ms"] or 0 for c in calls)}ms')
    for a in j["attempts"]:
        if not a["verdict"]["passed"]:
            pr = a["proposal"] or {}
            print(f'    attempt {a["attempt"]} rejected {pr.get("sport")}/{pr.get("intensity")}/{pr.get("duration_min")}/{pr.get("location")}: '
                  + "; ".join(v["rule_id"] for v in a["verdict"]["violations"]))
print(f"total tokens {tot_in}+{tot_out}, cost at $0.10/$0.50 per MTok: ${(tot_in*0.10 + tot_out*0.50)/1e6:.4f}")
