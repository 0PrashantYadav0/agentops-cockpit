#!/usr/bin/env bash
# =============================================================================
# AgentOps Cockpit -- one-command demo driver (screen-record this).
# REAL services: Llama 3.2 on Ollama + a self-hosted SigNoz. No API keys.
#
# Prereqs:
#   - Ollama:  ollama serve ; ollama pull llama3.2:1b ; ollama pull nomic-embed-text
#   - SigNoz:  up via Foundry (see deploy/signoz/README.md), OTLP on :4318
#
#   chmod +x demo.sh && ./demo.sh
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
export PYTHONPATH=src
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4318}"
COCKPIT_PORT=8100

pause() { sleep "${1:-2}"; }
banner() { echo; echo "=============================================================="; \
           echo ">>> $1"; echo "=============================================================="; echo; }

cleanup() { pkill -f "uvicorn agentops.cockpit" 2>/dev/null || true; }
trap cleanup EXIT

banner "0. PREFLIGHT  --  confirm the REAL services are up"
$PY - <<'PY'
from agentops import llm_client
from agentops.telemetry_store import SigNozClient
print("Ollama reachable :", llm_client.is_up())
print("SigNoz reachable :", SigNozClient().is_up())
PY
pause 2

banner "1. THE PITCH  --  real observability + auto-triage for AI agents on SigNoz"
echo "Real LLM (Llama 3.2 / Ollama), real Wikipedia search, real embeddings,"
echo "real SigNoz backend. No mocks, no API keys."
pause 3

banner "2. TESTS  --  11 tests (incl. a real Ollama integration test)"
$PY -m pytest -q
pause 2

banner "3. RUN THE AGENT  --  real LLM -> real tools -> exported to real SigNoz"
$PY -m agentops.run_demo --runs 10
pause 2

banner "4. PROOF: telemetry is really in SigNoz (query its ClickHouse store)"
if command -v docker >/dev/null 2>&1; then
  docker exec signoz-telemetrystore-clickhouse-0-0 clickhouse-client -q \
   "SELECT name, count() AS spans, sum(has_error) AS errors FROM signoz_traces.distributed_signoz_index_v3 WHERE resource_string_service\$\$name='agentops-demo-agent' GROUP BY name ORDER BY spans DESC FORMAT PrettyCompactMonoBlock" || \
   echo "(clickhouse query skipped -- is the SigNoz stack running?)"
fi
pause 3

banner "5. TRIAGE COPILOT  --  root cause + suggested fix per incident"
$PY -m agentops.triage_cli | sed -n '1,40p'
pause 4

banner "6. WEB COCKPIT  --  http://127.0.0.1:$COCKPIT_PORT"
.venv/bin/uvicorn agentops.cockpit:app --port $COCKPIT_PORT --host 127.0.0.1 > /tmp/agentops_cockpit.log 2>&1 &
sleep 5
curl -s -o /dev/null -w "cockpit GET / -> HTTP %{http_code}\n" http://127.0.0.1:$COCKPIT_PORT/
echo "Open http://127.0.0.1:$COCKPIT_PORT in a browser (show it on screen)."
echo "Press ENTER when done to finish the demo."
read -r _

banner "DONE  --  real traces + real cost + real triage, all on SigNoz"
