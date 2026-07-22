# Bring up real SigNoz (Foundry) for AgentOps Cockpit

SigNoz deprecated raw `docker-compose` in favour of **Foundry**. These files let you reproduce the
exact stack AgentOps was validated against (SigNoz + OTLP + **MCP server**).

## Files
- `casting.yaml` — the Foundry install spec (Docker Compose flavour, **MCP enabled**).
- `compose.generated.patched.yaml` — the compose Foundry generated from `casting.yaml`, with one
  local patch (see note below).

## Steps (on a machine with a healthy Docker runtime)
```bash
# 1. get foundryctl
curl -fsSL https://signoz.io/foundry.sh | bash
#    (or build: git clone https://github.com/SigNoz/foundry && cd foundry \
#     && GOPROXY=direct GOSUMDB=off go build -o foundryctl ./cmd/foundryctl)

# 2a. simplest: let Foundry drive it
foundryctl cast -f casting.yaml

# 2b. or use the generated compose directly
docker compose -f compose.generated.patched.yaml up -d
```
- SigNoz UI: http://localhost:8080
- OTLP: localhost:4317 (gRPC) / 4318 (HTTP)
- MCP server: http://localhost:8000/mcp  (mint an API key in the UI → Settings → API Keys)

Then run the agent against it:
```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
  PYTHONPATH=src .venv/bin/python -m agentops.run_demo --runs 24
```

## Note on the patch (ClickHouse-Keeper)
The generated compose pins `clickhouse/clickhouse-keeper` and `clickhouse-server`. On **Rancher
Desktop's VM kernel**, the standalone `clickhouse-keeper` binary **segfaults on startup (exit 139)**
before logging — reproduced across versions 23.8 / 24.1 / 24.8 / 25.12. The plain `clickhouse server`
and `clickhouse local` run fine there, so it is a keeper-daemon/kernel incompatibility, not a config
error. The patched compose runs keeper via the full `clickhouse` multicall binary
(`/usr/bin/clickhouse keeper`) from the `clickhouse-server` image; this still segfaults on that
specific kernel but works on Docker Desktop / OrbStack / Linux.

**If keeper won't start on your host:** use Docker Desktop or OrbStack instead of Rancher Desktop,
give the VM ≥ 8 GiB RAM, or deploy SigNoz on a Linux host. The AgentOps agent, dashboards, and
alerts are unchanged — only the backend host matters.
