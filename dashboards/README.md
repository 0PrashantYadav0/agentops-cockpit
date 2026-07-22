# SigNoz dashboard pack + alerts

## Import the dashboard
1. Open the SigNoz UI (`http://localhost:8080`) → **Dashboards** → **New dashboard** → **Import JSON**.
2. Upload `agentops-signoz-dashboard.json`.
3. Run the demo workload so panels populate:
   `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 PYTHONPATH=src .venv/bin/python -m agentops.run_demo --runs 24`

Panels: total token cost, cost by model, cost by user, agent-run p95 latency, error rate by span.

## Alerts to configure (Alerts → New alert)
| Alert | Signal | Condition | Why |
|-------|--------|-----------|-----|
| **Budget spike** | traces | `sum(gen_ai.usage.cost_usd)` over 5m > your $ threshold | catch runaway generations |
| **Per-run cost** | traces | any trace `sum(gen_ai.usage.cost_usd)` > 0.004 | catch a single expensive run |
| **Agent error rate** | traces | `count(has_error=true)` / `count()` > 10% | reliability regression |
| **p95 latency** | traces | `p95(duration_nano)` on `agent.run` > 1.5s | latency regression |
| **Tool failure** | traces | `count(has_error=true)` grouped by `tool.name` > 0 | flaky tool/retrieval |

These map 1:1 to the thresholds the Triage Copilot uses in `src/agentops/triage.py`, so the CLI/web
triage and the SigNoz alerts tell the same story.
