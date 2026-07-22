"""CLI triage: print the fleet + per-trace triage report.

Run:  python -m agentops.triage_cli
"""
from __future__ import annotations

from .telemetry_store import SigNozClient, compute_analytics, load_traces
from .triage import fleet_alerts, triage_all


def main() -> None:
    traces = load_traces()
    if not traces:
        print("No telemetry found. Run `python -m agentops.run_demo` first.")
        return

    a = compute_analytics(traces)
    signoz_up = SigNozClient().is_up()

    print("=" * 68)
    print("AGENTOPS COCKPIT -- TRIAGE REPORT")
    print("=" * 68)
    print(f"SigNoz backend reachable : {signoz_up}")
    print(f"Total agent runs         : {a.total_traces}")
    print(f"Failed runs              : {a.error_traces}  (error rate {a.error_rate:.0%})")
    print(f"Total spend              : ${a.total_cost_usd:.4f}")
    print(f"Total tokens             : {a.total_tokens:,}")
    print(f"Latency p50 / p95        : {a.p50_latency_ms:.0f}ms / {a.p95_latency_ms:.0f}ms")
    print(f"Cost by model            : {a.cost_by_model}")
    print(f"Cost by user             : {a.cost_by_user}")

    print("\n--- FLEET ALERTS " + "-" * 51)
    alerts = fleet_alerts(a)
    if alerts:
        for al in alerts:
            print(f"  [!] {al}")
    else:
        print("  (none)")

    print("\n--- PER-INCIDENT TRIAGE " + "-" * 44)
    reports = triage_all(traces)
    if not reports:
        print("  No incidents detected. Fleet healthy.")
    for r in reports:
        print()
        print(r.as_markdown())


if __name__ == "__main__":
    main()
