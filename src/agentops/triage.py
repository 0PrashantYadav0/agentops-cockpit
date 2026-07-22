"""Triage Copilot.

When something goes wrong, this scans the telemetry (the same data in SigNoz),
finds the offending traces, and produces a plain-English root cause + suggested
fix -- the "point your agent at the data and let it debug" experience.

It is LLM-shaped: ``LocalReasoner`` is a deterministic, no-API-key analyst that
inspects span attributes and error statuses. Swap in a real LLM (or the SigNoz
MCP server) by implementing the same ``diagnose`` signature.
"""
from __future__ import annotations

from dataclasses import dataclass

from .telemetry_store import Analytics, TraceSummary

# thresholds an SRE would set as SigNoz alerts
COST_PER_TRACE_ALERT_USD = 0.004
P95_LATENCY_ALERT_MS = 1500.0
ERROR_RATE_ALERT = 0.10


@dataclass
class TriageReport:
    title: str
    severity: str
    trace_id: str | None
    root_cause: str
    suggested_fix: str
    evidence: list[str]

    def as_markdown(self) -> str:
        ev = "\n".join(f"  - {e}" for e in self.evidence)
        tid = self.trace_id or "n/a"
        return (
            f"### [{self.severity}] {self.title}\n"
            f"- **Trace:** `{tid}`\n"
            f"- **Root cause:** {self.root_cause}\n"
            f"- **Suggested fix:** {self.suggested_fix}\n"
            f"- **Evidence:**\n{ev}\n"
        )


class LocalReasoner:
    """Deterministic root-cause analysis over span data."""

    def diagnose_trace(self, trace: TraceSummary) -> TriageReport | None:
        # 1) hard failures win
        errs = trace.error_spans()
        if errs:
            span = errs[0]
            name = span["name"]
            msg = span.get("status_message") or "unknown error"
            comp = span["attributes"].get("tool.name") or span["attributes"].get(
                "gen_ai.request.model", name
            )
            return TriageReport(
                title=f"Failure in {name}",
                severity="CRITICAL",
                trace_id=trace.trace_id,
                root_cause=(
                    f"Span `{name}` (component `{comp}`) failed with: {msg}. "
                    f"This aborted the agent run for user `{trace.user_id}`."
                ),
                suggested_fix=_fix_for(name, msg),
                evidence=[
                    f"status=ERROR on span '{name}'",
                    f"message: {msg}",
                    f"scenario tag: {trace.scenario}",
                ],
            )
        # 2) cost anomaly
        if trace.total_cost_usd >= COST_PER_TRACE_ALERT_USD:
            worst = max(
                trace.spans,
                key=lambda s: float(s["attributes"].get("gen_ai.usage.cost_usd", 0)),
            )
            out_tok = worst["attributes"].get("gen_ai.usage.output_tokens", "?")
            model = worst["attributes"].get("gen_ai.request.model", "?")
            return TriageReport(
                title="Cost spike on a single run",
                severity="HIGH",
                trace_id=trace.trace_id,
                root_cause=(
                    f"Run cost ${trace.total_cost_usd:.4f} (>{COST_PER_TRACE_ALERT_USD}). "
                    f"Driven by `{worst['name']}` on `{model}` generating "
                    f"{out_tok} output tokens -- likely a runaway/verbose completion."
                ),
                suggested_fix=(
                    "Set max_output_tokens, tighten the synthesis prompt, or route this "
                    "step to a cheaper model (e.g. gpt-4o-mini) and add a SigNoz "
                    "budget-spike alert on gen_ai.usage.cost_usd."
                ),
                evidence=[
                    f"trace cost = ${trace.total_cost_usd:.4f}",
                    f"biggest span: {worst['name']} ({out_tok} output tokens)",
                ],
            )
        # 3) latency anomaly
        if trace.duration_ms >= P95_LATENCY_ALERT_MS:
            slow = max(trace.spans, key=lambda s: s.get("duration_ms", 0))
            return TriageReport(
                title="Latency spike on a single run",
                severity="MEDIUM",
                trace_id=trace.trace_id,
                root_cause=(
                    f"Run took {trace.duration_ms:.0f}ms. Slowest step: "
                    f"`{slow['name']}` at {slow['duration_ms']:.0f}ms."
                ),
                suggested_fix=(
                    "Add a timeout + retry on the slow step, parallelise independent "
                    "tool calls, or cache retrievals. Alert on p95 duration in SigNoz."
                ),
                evidence=[
                    f"trace duration = {trace.duration_ms:.0f}ms",
                    f"slowest span: {slow['name']} = {slow['duration_ms']:.0f}ms",
                ],
            )
        return None


def _fix_for(span_name: str, msg: str) -> str:
    low = (span_name + " " + msg).lower()
    if "web_search" in low or "timed out" in low:
        return (
            "Wrap web_search in a timeout + exponential-backoff retry and add a "
            "fallback source. Add a SigNoz alert on tool.web_search error rate."
        )
    if "vector_db" in low or "connection" in low:
        return (
            "Add a health check + connection pool with retries for the vector DB; "
            "degrade gracefully to keyword search. Alert on tool.vector_db errors."
        )
    if "503" in low or "outage" in low or "gen_ai" in low:
        return (
            "Add provider failover (secondary model/region) and circuit-breaker; "
            "queue and retry on 5xx. Alert on gen_ai.chat error rate in SigNoz."
        )
    return "Add error handling + retry around the failing span and alert on it in SigNoz."


def triage_all(traces: list[TraceSummary]) -> list[TriageReport]:
    reasoner = LocalReasoner()
    reports: list[TriageReport] = []
    for t in traces:
        r = reasoner.diagnose_trace(t)
        if r:
            reports.append(r)
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    reports.sort(key=lambda r: sev_order.get(r.severity, 9))
    return reports


def fleet_alerts(a: Analytics) -> list[str]:
    """SigNoz-style fleet-level alerts derived from the aggregate metrics."""
    out: list[str] = []
    if a.error_rate >= ERROR_RATE_ALERT:
        out.append(
            f"ERROR-RATE alert: {a.error_rate:.0%} of runs failed "
            f"({a.error_traces}/{a.total_traces})."
        )
    if a.p95_latency_ms >= P95_LATENCY_ALERT_MS:
        out.append(f"LATENCY alert: p95 run latency = {a.p95_latency_ms:.0f}ms.")
    return out
