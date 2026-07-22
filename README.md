# AgentOps Cockpit

> **Real observability + auto-triage for AI agents, powered by SigNoz.**
> Theme 1 · Idea 1 of the *Agents of SigNoz* hackathon (the #1-ranked idea, 53/60).

If you can't observe your AI agents, you don't own them. AgentOps Cockpit instruments a **real** AI
agent (a **Llama 3.2 model on Ollama**, live **Wikipedia** search, and **real embedding retrieval**)
with OpenTelemetry using the **GenAI semantic conventions**, streams the traces to a **real,
self-hosted SigNoz**, tracks **token cost per model/user/run**, and ships a **Triage Copilot** that
reads the telemetry and explains *what broke and how to fix it*.

****No mocks. No API keys** (the LLM is self-hosted on Ollama).

---

## Documentation
| Doc | What it covers |
|-----|----------------|
| **[SETUP.md](SETUP.md)** | Step-by-step setup: Ollama, SigNoz-via-Foundry (with the ZooKeeper fix), install, run, verify, troubleshoot. |
| **[AGENT.md](AGENT.md)** | Deep dive: the agent's design, span model, GenAI conventions, cost model, failure scenarios, Triage Copilot, and how to extend it. |
| **[SUBMISSION.md](SUBMISSION.md)** | How to submit to the *Agents of SigNoz* hackathon + side tracks. |
| **[VIDEO_SCRIPT.md](VIDEO_SCRIPT.md)** | The rendered demo video (`video/AgentOps-Cockpit-demo.mp4`, ~3.3 min) + how it's built. |
| **[dashboards/README.md](dashboards/README.md)** | Import the SigNoz dashboard pack + configure alerts. |
| **[deploy/signoz/README.md](deploy/signoz/README.md)** | Bring up real SigNoz with Foundry (Keeper->ZooKeeper fix). |

> A narrated demo video is already rendered at **`video/AgentOps-Cockpit-demo.mp4`** (~3.3 min, built from real runs).

---

## Requirements (two real services, both free / local)
1. **Ollama** — `ollama serve`, then `ollama pull llama3.2:1b` and `ollama pull nomic-embed-text`
   (optional `ollama pull llama3.2:3b` for the latency scenario).
2. **SigNoz** — self-hosted via **Foundry** (see `deploy/signoz/README.md`); OTLP on `:4318`, UI `:8080`.

No LLM API keys are needed. Copy `.env.example` to `.env` only if your endpoints differ.

---

## What's in the box
```
src/agentops/
  cost.py            # token -> USD cost model (real Ollama models)
  ledger.py          # local JSONL span sink (mirror of what's exported + triage source)
  instrument.py      # OTel setup + gen_ai/tool span context managers  -> SigNoz OTLP + ledger
  llm_client.py      # REAL LLM client (Ollama chat + embeddings), real token accounting
  tools_real.py      # REAL tools: Wikipedia search + embedding-based vector retrieval
  agent.py           # demo research agent (plan -> web_search -> vector_db -> synthesise)
  telemetry_store.py # SigNoz client + trace analytics (cost/latency/error rate)
  triage.py          # Triage Copilot: root-cause + suggested fix per incident
  run_demo.py        # workload generator (healthy + REAL failure scenarios)
  triage_cli.py      # CLI triage report
  cockpit.py         # FastAPI + HTMX + Tailwind + Chart.js web dashboard
  otlp_receiver.py   # optional local OTLP receiver (offline wire-export demo)
tests/               # pytest: unit (LLM-free) + real Ollama integration (auto-skips if down)
deploy/signoz/       # Foundry casting + patched compose to bring up real SigNoz
dashboards/          # importable SigNoz dashboard pack + alerts guide
video/               # narrated demo video + builder (build_video.py) + captures
```

The failure scenarios are **real**, not simulated:
- `llm_outage` → calls a non-existent model → real Ollama 404.
- `vector_failure` → embeds with a non-existent model → real 404.
- `tool_failure` → fetches a non-existent Wikipedia page → real HTTP error.
- `cost_spike` / `latency_spike` → real long generation / real bigger model.

---

## Quickstart
```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"

# services up: `ollama serve` (+ pulls) and SigNoz via Foundry (deploy/signoz/README.md)

.venv/bin/python -m pytest -q                                   # 11 passed
PYTHONPATH=src .venv/bin/python -m agentops.run_demo --runs 10  # real LLM -> real SigNoz
PYTHONPATH=src .venv/bin/python -m agentops.triage_cli          # root cause + fix
PYTHONPATH=src .venv/bin/uvicorn agentops.cockpit:app --port 8100   # http://127.0.0.1:8100
# ...or just: ./demo.sh
```

Verify the traces really landed in SigNoz:
```bash
docker exec signoz-telemetrystore-clickhouse-0-0 clickhouse-client -q \
 "SELECT name, count() spans, sum(has_error) errors
  FROM signoz_traces.distributed_signoz_index_v3
  WHERE resource_string_service\$\$name='agentops-demo-agent' GROUP BY name ORDER BY spans DESC"
```

Import `dashboards/agentops-signoz-dashboard.json` into the SigNoz UI for the cost/latency/error
panels, and wire the alerts in `dashboards/README.md`.

---

## How it uses SigNoz deeply (Best Use of SigNoz)
- **Traces** — every agent run is one trace; real LLM/tool/retrieval steps are child spans.
- **GenAI conventions** — `gen_ai.request.model`, `gen_ai.usage.input_tokens/output_tokens`, and a
  custom `gen_ai.usage.cost_usd` computed from the model's **real** token counts.
- **Metrics/dashboards** — cost by model/user, p50/p95 latency, error rate (dashboard pack included).
- **Alerts** — budget-spike, error-rate, and p95-latency alerts (thresholds match the triage logic).
- **MCP** — the Triage Copilot is built to query telemetry via the SigNoz MCP server (enabled in the
  Foundry casting); the local `LocalReasoner` is the offline stand-in with the same interface.

---

## Verified end-to-end against REAL services (2026-07-10)
| Step | Result |
|------|--------|
| `pytest` | **11 passed** (incl. real Ollama integration tests) |
| Real workload | 8 ok / 2 real failures (missing model + missing embed model) |
| **Real SigNoz store** | **111 spans / 26 traces** in ClickHouse; 43 `gen_ai.chat` (2 errors), real cost + **4,697 real output tokens** from `llama3.2:1b` |
| Triage Copilot | CRITICAL failures, cost/latency incidents + fleet alerts, each with a fix |
| Web cockpit | HTTP 200, live cost charts + triage feed |
| Demo video | `video/AgentOps-Cockpit-demo.mp4` (3.3 min, narrated) |

> **SigNoz on Rancher Desktop note:** SigNoz's bundled ClickHouse-**Keeper** segfaults on Rancher
> Desktop's VM kernel. The included compose (`deploy/signoz/`) fixes this by running a **real Apache
> ZooKeeper** as the coordination service (ClickHouse Keeper speaks the ZK protocol, so it's a
> drop-in). With that swap the full real stack — ClickHouse, collector, apiserver, MCP — runs
> healthy. On Docker Desktop / OrbStack / Linux the stock keeper works too.

---

## Design notes
- **Real, swappable brain** — `LocalReasoner` implements the triage interface deterministically; a
  hosted LLM or the SigNoz MCP client drops in without touching the pipeline.
- **Never break the observed app** — the ledger exporter and cost lookup swallow their own errors.
- **Dual sink** — spans go to SigNoz *and* a local ledger (same data), so triage/tests never diverge.
- **DRY/YAGNI** — one small pricing table, one span model; every module is small and testable.
