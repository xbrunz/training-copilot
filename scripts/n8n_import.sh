#!/bin/sh
# Import (or update) the workflows in the running n8n container.
set -eu
cd "$(dirname "$0")/.."
for f in workflows/*.json; do
  docker compose exec -T n8n sh -c 'cat > /tmp/wf.json' < "$f"
  docker compose exec -T n8n sh -c 'n8n import:workflow --input=/tmp/wf.json 2>&1 | grep -iE "import|error"; rm -f /tmp/wf.json'
done
# Sub-workflows must be published to be callable (n8n 2.x). The main workflow's
# schedule trigger stays disabled in the JSON until it is meant to run nightly.
docker compose exec -T n8n sh -c 'n8n publish:workflow --id=TrainCopilotMain 2>&1 | grep -iE "publish|error"'
docker compose restart n8n >/dev/null && echo "n8n restarted to load published workflows"
