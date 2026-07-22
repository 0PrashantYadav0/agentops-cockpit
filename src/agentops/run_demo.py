"""Generate a realistic agent workload and stream it to SigNoz + the ledger.

Run:  python -m agentops.run_demo [--no-otlp] [--runs N]

It fires a mix of healthy and failing runs across several users so the cockpit
and triage copilot have real incidents (cost spikes, latency, tool failures,
LLM outage) to surface.
"""
from __future__ import annotations

import argparse
import random
import time

from .agent import SCENARIOS, run_agent
from .instrument import flush, setup_telemetry
from .ledger import clear_ledger
from .telemetry_store import SigNozClient

QUESTIONS = [
    "OpenTelemetry",
    "Distributed tracing",
    "Observability",
    "Large language model",
    "Kubernetes",
    "Vector database",
]
USERS = ["alice", "bob", "carol", "dave"]

# weighted scenario mix: mostly healthy, sprinkled failures
WEIGHTED = (
    ["healthy"] * 10
    + ["cost_spike"] * 2
    + ["latency_spike"] * 2
    + ["tool_failure"] * 2
    + ["vector_failure"] * 1
    + ["llm_outage"] * 1
)


def main() -> None:
    ap = argparse.ArgumentParser(description="AgentOps demo workload")
    ap.add_argument("--no-otlp", action="store_true", help="ledger only, skip SigNoz")
    ap.add_argument("--runs", type=int, default=24, help="number of agent runs")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    clear_ledger()
    setup_telemetry(enable_otlp=not args.no_otlp)

    if not args.no_otlp:
        up = SigNozClient().is_up()
        print(f"[agentops] SigNoz reachable: {up} (telemetry also saved to ledger)")

    ok = fail = 0
    for i in range(args.runs):
        q = rng.choice(QUESTIONS)
        user = rng.choice(USERS)
        sc = SCENARIOS[rng.choice(WEIGHTED)]
        try:
            time.sleep(1.5)
            run_agent(q, user_id=user, scenario=sc)
            ok += 1
            print(f"  run {i+1:>2}/{args.runs} [{sc.name:<14}] user={user:<5} OK")
        except Exception as exc:  # expected for failure scenarios
            fail += 1
            print(f"  run {i+1:>2}/{args.runs} [{sc.name:<14}] user={user:<5} FAILED: {exc}")

    flush()
    print(f"\n[agentops] done: {ok} ok, {fail} failed. Telemetry -> ledger + SigNoz.")
    print("[agentops] next: `python -m agentops.triage_cli` or start the cockpit.")


if __name__ == "__main__":
    main()
