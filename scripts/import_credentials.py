"""Create or update the n8n credentials from .env, without secrets touching disk.

The credential JSON is streamed into the n8n container, imported (n8n encrypts it
with N8N_ENCRYPTION_KEY), then deleted. IDs are fixed so the committed workflow
JSON can reference credentials by ID while containing no secrets.

Usage (stack running, n8n owner account created):  python3 scripts/import_credentials.py
"""
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
env = dict(l.strip().split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l)

credentials = [
    {"id": "pgCopilotWriter1", "name": "Postgres copilot_writer", "type": "postgres",
     "data": {"host": "postgres", "port": 5432, "database": "copilot", "user": "copilot_writer",
              "password": env["COPILOT_WRITER_PASSWORD"], "ssl": "disable", "allowUnauthorizedCerts": False}},
    {"id": "intervalsApiKey1", "name": "intervals.icu API key", "type": "httpBasicAuth",
     "data": {"user": "API_KEY", "password": env["INTERVALS_API_KEY"]}},
]
optional = {
    "ANTHROPIC_API_KEY": {"id": "anthropicApiKey1", "name": "Anthropic API key", "type": "httpHeaderAuth",
                          "data": {"name": "x-api-key", "value": None}},
    "TELEGRAM_BOT_TOKEN": {"id": "telegramBot00001", "name": "Telegram bot", "type": "telegramApi",
                           "data": {"accessToken": None}},
}
for key, cred in optional.items():
    if env.get(key):
        field = "value" if "value" in cred["data"] else "accessToken"
        cred["data"][field] = env[key]
        credentials.append(cred)


def n8n(cmd, stdin=None):
    return subprocess.run(["docker", "compose", "exec", "-T", "n8n", "sh", "-c", cmd],
                          input=stdin, capture_output=True, text=True, cwd=ROOT)


n8n("umask 077; cat > /tmp/creds.json", stdin=json.dumps(credentials))
result = n8n("n8n import:credentials --input=/tmp/creds.json; rm -f /tmp/creds.json")
print([l for l in (result.stdout + result.stderr).splitlines() if "credential" in l.lower()][-1])
print("imported:", ", ".join(c["name"] for c in credentials))
