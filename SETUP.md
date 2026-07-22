# SETUP.md — AgentOps Cockpit

Complete, reproducible setup for the **real** stack: a self-hosted LLM (Ollama) + a self-hosted
SigNoz backend. No API keys anywhere.

- **Time to first traces:** ~10–15 min (mostly image/model downloads).
- **Tested on:** macOS (Apple Silicon), Python 3.12, Rancher Desktop. Also works on Docker
  Desktop / OrbStack / Linux.

---

## 0. Prerequisites

| Tool | Why | Install |
|------|-----|---------|
| Python 3.12 + `uv` | run the agent + tests | `brew install uv` |
| Docker runtime | run SigNoz | Rancher Desktop / Docker Desktop / OrbStack |
| `docker compose` | bring up SigNoz | ships with the runtimes above (or `brew install docker-compose`) |
| Ollama | the real LLM | `brew install ollama` |
| Go 1.21+ (optional) | build `foundryctl` from source if the installer is blocked | `brew install go` |

> **Rancher Desktop note:** the docker credential helper lives in `~/.rd/bin`. If pulls fail with
> `docker-credential-osxkeychain ... not found`, prefix commands with
> `PATH="$HOME/.rd/bin:$PATH"`.

---

## 1. Real LLM — Ollama

```bash
ollama serve &                     # start the inference server (port 11434)
ollama pull llama3.2:1b            # chat model (plan + synthesise)
ollama pull nomic-embed-text       # embeddings for the vector-DB tool
ollama pull llama3.2:3b            # optional: heavier model for the latency scenario

# sanity check
curl -s http://localhost:11434/api/version
curl -s http://localhost:11434/api/generate \
  -d '{"model":"llama3.2:1b","prompt":"hello in 3 words","stream":false}'
```

---

## 2. Real SigNoz — via Foundry

SigNoz deprecated raw `docker-compose` in favour of **Foundry**. This repo ships the Foundry
`casting.yaml` (with the **MCP server** enabled) and a pre-generated, patched compose.

### 2a. Get `foundryctl`
```bash
# official installer:
curl -fsSL https://signoz.io/foundry.sh | bash
# ...or build from source (if the installer host is blocked):
git clone https://github.com/SigNoz/foundry && cd foundry
GOPROXY=direct GOSUMDB=off go build -o /usr/local/bin/foundryctl ./cmd/foundryctl
```

### 2b. Bring it up
```bash
cd deploy/signoz
# simplest — let Foundry drive it:
foundryctl cast -f casting.yaml
# ...or use the pre-generated patched compose directly:
PATH="$HOME/.rd/bin:$PATH" docker compose -f compose.generated.patched.yaml up -d
```

Endpoints once healthy:
- SigNoz UI: <http://localhost:8080>
- OTLP: `localhost:4317` (gRPC) / `localhost:4318` (HTTP)
- MCP server: <http://localhost:8000/mcp> (mint an API key in the UI → Settings → API Keys)

### 2c. The ClickHouse-Keeper → ZooKeeper fix (important on Rancher Desktop)
SigNoz's bundled **ClickHouse-Keeper segfaults (exit 139)** on Rancher Desktop's VM kernel — it
crashes before logging, across every ClickHouse version. The plain `clickhouse server` runs fine, so
it's a keeper-daemon/kernel issue, not a config error.

**Fix (already applied in `compose.generated.patched.yaml`):** run a **real Apache ZooKeeper** as the
coordination service. ClickHouse Keeper speaks the ZooKeeper protocol, so ZooKeeper is a drop-in:
- keeper service image → `zookeeper:3.9` (listens on 2181)
- ClickHouse config `zookeeper.port` → `2181`

If you deploy on **Docker Desktop / OrbStack / Linux**, the stock keeper usually works and no patch
is needed — use `foundryctl cast` directly.

### 2d. Verify SigNoz is up
```bash
curl -s localhost:8080/api/v1/version         # {"version":"v0.132.x",...,"setupCompleted":...}
curl -s -o /dev/null -w "OTLP %{http_code}\n" -X POST localhost:4318/v1/traces \
  -H "Content-Type: application/json" -d '{"resourceSpans":[]}'   # expect 200
PATH="$HOME/.rd/bin:$PATH" docker ps --format "{{.Names}} {{.Status}}" | grep signoz
```

---

## 3. Install the project

```bash
cd agentops-cockpit
uv venv --python 3.12
uv pip install -e ".[dev]"

cp .env.example .env       # optional — only edit if your endpoints differ
```

---

## 4. Run everything

```bash
# tests (unit + real Ollama integration; integration auto-skips if Ollama is down)
.venv/bin/python -m pytest -q                                  # 11 passed

# real workload -> real SigNoz  (OTLP endpoint defaults to http://localhost:4318)
PYTHONPATH=src .venv/bin/python -m agentops.run_demo --runs 12

# triage report (root cause + suggested fix)
PYTHONPATH=src .venv/bin/python -m agentops.triage_cli

# web cockpit
PYTHONPATH=src .venv/bin/uvicorn agentops.cockpit:app --port 8100   # http://127.0.0.1:8100

# ...or the one-command guided demo:
./demo.sh
```

### Verify the traces really landed in SigNoz
```bash
PATH="$HOME/.rd/bin:$PATH" docker exec signoz-telemetrystore-clickhouse-0-0 \
  clickhouse-client -q "SELECT name, count() spans, sum(has_error) errors
    FROM signoz_traces.distributed_signoz_index_v3
    WHERE resource_string_service\$\$name='agentops-demo-agent'
    GROUP BY name ORDER BY spans DESC FORMAT PrettyCompactMonoBlock"
```
Or open the SigNoz UI → **Traces** and filter `service.name = agentops-demo-agent`.

---

## 5. Environment variables (all optional — defaults shown)

| Var | Default | Purpose |
|-----|---------|---------|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server |
| `AGENTOPS_MODEL` | `llama3.2:1b` | chat model (plan + synthesise) |
| `AGENTOPS_BIG_MODEL` | `llama3.2:3b` | heavier model for the latency scenario |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | SigNoz OTLP/HTTP endpoint |
| `OTEL_SERVICE_NAME` | `agentops-demo-agent` | service name in SigNoz |
| `DEPLOYMENT_ENVIRONMENT` | `hackathon` | env tag on spans |
| `SIGNOZ_URL` | `http://localhost:8080` | SigNoz UI (health + deep-links) |
| `AGENTOPS_LEDGER` | `./data/ledger.jsonl` | local mirror of exported spans |

There is **no LLM API key** — the model is self-hosted.

---

## 6. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `docker-credential-osxkeychain ... not found` | prefix commands with `PATH="$HOME/.rd/bin:$PATH"` (Rancher Desktop) |
| ClickHouse-Keeper container `Restarting (139)` | use the ZooKeeper patch (§2c) or switch to Docker Desktop/OrbStack |
| `run_demo` shows `web_search API failed: HTTP 429` | Wikipedia rate-limited you; the tool retries once, and `run_demo` spaces requests — just rerun |
| `web_search: no results` | rare for real topics; the demo uses Wikipedia-friendly queries |
| integration tests skipped | Ollama isn't running — `ollama serve` + pull models |
| OTLP POST returns non-200 | SigNoz ingester still starting or ClickHouse not healthy — wait, recheck §2d |
| cockpit charts empty | run `run_demo` first to populate the ledger, then reload |

---

## 7. Teardown

```bash
# stop the cockpit / any demo servers
pkill -f "uvicorn agentops.cockpit" ; pkill -f "agentops.otlp_receiver"
# stop SigNoz (keep data)
cd deploy/signoz && PATH="$HOME/.rd/bin:$PATH" docker compose -f compose.generated.patched.yaml down
# ...or wipe volumes too:  docker compose -f compose.generated.patched.yaml down -v
# stop Ollama
pkill -f "ollama serve"
```
