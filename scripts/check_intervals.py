"""Coverage check for intervals.icu wellness and activities.

Prints counts per field only, never values, so output is safe to share.
Usage: python3 scripts/check_intervals.py [days]   (reads .env; uses curl for TLS)
"""
import base64, datetime, json, subprocess, sys

env = dict(l.strip().split("=", 1) for l in open(".env") if "=" in l)
auth = base64.b64encode(f"API_KEY:{env['INTERVALS_API_KEY']}".encode()).decode()
days = int(sys.argv[1]) if len(sys.argv) > 1 else 14


def get(path):
    url = f"https://intervals.icu/api/v1/athlete/{env['INTERVALS_ATHLETE_ID']}{path}"
    cfg = f'url = "{url}"\nheader = "Authorization: Basic {auth}"\nsilent\nwrite-out = "\\n%{{http_code}}"\n'
    body, _, code = subprocess.run(["curl", "-K", "-"], input=cfg, capture_output=True, text=True).stdout.rpartition("\n")
    if code != "200":
        sys.exit(f"HTTP {code} on {path.split('?')[0]}")
    return json.loads(body)


today = datetime.date.today()
window = f"oldest={today - datetime.timedelta(days=days)}&newest={today}"
wellness = get(f"/wellness?{window}")
print(f"wellness: {len(wellness)} days in last {days}")
for k in ["hrv", "restingHR", "sleepSecs", "sleepScore", "readiness", "ctl", "atl"]:
    print(f"  {k:10s} {sum(1 for d in wellness if d.get(k) not in (None, 0))}/{len(wellness)}")
activities = get(f"/activities?{window}")
print(f"activities: {len(activities)} | types: {sorted({a.get('type') for a in activities})}")
print(f"  with training load: {sum(1 for a in activities if a.get('icu_training_load'))}")
