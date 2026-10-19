"""Generate anonymised sample scenarios in intervals.icu / Open-Meteo response shape.

Synthetic data only: no real health data is ever committed. Each scenario
varies one or two signals so the guardrails and the agent get exercised.
Deterministic (fixed seed), so re-running gives the same files.

Usage: python3 scripts/make_scenarios.py
"""
import datetime as dt
import json
import pathlib
import random

OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "sample" / "scenarios"
PLAN = json.loads((OUT.parent.parent / "plan" / "weekly_plan.json").read_text())

# Illustrative training load per planned session type (not a physiological model)
LOAD = {("run", "hard"): 70, ("run", "easy"): 85, ("swim", "moderate"): 45, ("bike", "hard"): 75,
        ("bike", "easy"): 130, ("strength", "moderate"): 30}
TYPE = {"run": "Run", "swim": "Swim", "strength": "WeightTraining"}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def base(target: dt.date, rng: random.Random):
    today = target - dt.timedelta(days=1)
    wellness, activities = [], []
    ctl = 50.0
    for back in range(13, -1, -1):
        day = today - dt.timedelta(days=back)
        ctl += rng.uniform(-0.2, 0.5)
        wellness.append({
            "id": day.isoformat(),
            "hrv": round(rng.gauss(62, 3)),
            "restingHR": round(rng.gauss(49, 1)),
            "sleepSecs": int(rng.gauss(7.4, 0.35) * 3600),
            "sleepScore": round(rng.gauss(81, 4)),
            "ctl": round(ctl, 1),
            "atl": round(ctl + rng.uniform(-3, 8), 1),
        })
        p = PLAN["week"][WEEKDAYS[day.weekday()]]
        if p["sport"] != "rest":
            t = "VirtualRide" if p["sport"] == "bike" and p["location"] == "trainer" else TYPE.get(p["sport"], "Ride")
            activities.append({
                "id": f"a{day:%m%d}",
                "start_date_local": f"{day.isoformat()}T07:{rng.randint(0, 59):02d}:00",
                "type": t,
                "moving_time": p["duration_min"] * 60,
                "icu_training_load": round(LOAD[(p["sport"], p["intensity"])] * rng.uniform(0.85, 1.15)),
            })
    weather = {"daily": {
        "time": [target.isoformat()],
        "temperature_2m_min": [round(rng.uniform(12, 15), 1)],
        "temperature_2m_max": [round(rng.uniform(19, 23), 1)],
        "precipitation_sum": [0.0],
        "precipitation_probability_max": [rng.randint(0, 10)],
        "wind_speed_10m_max": [round(rng.uniform(10, 18), 1)],
        "wind_gusts_10m_max": [round(rng.uniform(25, 35), 1)],
    }}
    return wellness, activities, weather


def today_row(w):
    return w[-1]


def set_last(w, n, **vals):
    for r in w[-n:]:
        r.update(vals)


SCENARIOS = [
    ("s01_good_recovery_intervals", "2026-10-20", "Normal recovery, intervals planned, dry weather", lambda w, a, x: None),
    ("s02_low_hrv_hard_day", "2026-10-22", "HRV ~22% below 7-day baseline, hard trainer session planned",
     lambda w, a, x: today_row(w).update(hrv=48)),
    ("s03_short_sleep_hard_day", "2026-10-27", "4.8 h sleep, intervals planned",
     lambda w, a, x: today_row(w).update(sleepSecs=int(4.8 * 3600), sleepScore=44)),
    ("s04_load_spike", "2026-10-29", "Last 7 days ~60% more load than the previous 7",
     lambda w, a, x: [act.update(icu_training_load=round(act["icu_training_load"] * 1.6)) for act in a[-6:]]),
    ("s05_rain_long_ride", "2026-10-24", "Long outdoor ride planned, heavy rain and strong gusts forecast",
     lambda w, a, x: x["daily"].update(precipitation_sum=[14.2], precipitation_probability_max=[90],
                                       wind_speed_10m_max=[38.0], wind_gusts_10m_max=[66.0])),
    ("s06_planned_rest_day", "2026-10-26", "Rest day planned, recovery normal", lambda w, a, x: None),
    ("s07_high_fatigue", "2026-10-31", "Fatigue (ATL) ~25 above fitness (CTL), long ride planned",
     lambda w, a, x: set_last(w, 3, atl=round(today_row(w)["ctl"] + 25, 1))),
    ("s08_missing_wellness", "2026-11-03", "Watch not worn: no wellness data for the last 3 days",
     lambda w, a, x: w.__delitem__(slice(-3, None))),
    ("s09_elevated_rhr", "2026-10-25", "Resting HR +8 bpm and HRV ~12% below baseline, long run planned",
     lambda w, a, x: today_row(w).update(restingHR=57, hrv=55)),
    ("s10_no_rest_12_days", "2026-10-28", "Trained every day for 12 days, swim planned", None),
]


def no_rest(w, a, x):
    """Fill rest days with an easy 40 min trainer ride."""
    dates = {act["start_date_local"][:10] for act in a}
    for r in w[-12:]:
        if r["id"] not in dates:
            a.append({"id": f"a{r['id'][5:7]}{r['id'][8:]}x", "start_date_local": f"{r['id']}T18:00:00",
                      "type": "VirtualRide", "moving_time": 2400, "icu_training_load": 35})
    a.sort(key=lambda act: act["start_date_local"])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for i, (sid, target, desc, mutate) in enumerate(SCENARIOS):
        rng = random.Random(1000 + i)
        t = dt.date.fromisoformat(target)
        w, a, x = base(t, rng)
        (mutate or no_rest)(w, a, x)
        doc = {"scenario_id": sid, "description": desc, "synthetic": True, "target_date": target,
               "wellness": w, "activities": a, "weather": x}
        (OUT / f"{sid}.json").write_text(json.dumps(doc, indent=1) + "\n")
        print(f"{sid:30s} {target} {PLAN['week'][WEEKDAYS[t.weekday()]]['sport']:8s} {desc}")


if __name__ == "__main__":
    main()
