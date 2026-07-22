"""Unit tests for analytics + triage over synthetic telemetry.

These build TraceSummary objects directly from span dicts (the exact ledger
schema), so they need no LLM and no backend -- fast and deterministic.
"""
from agentops.telemetry_store import TraceSummary, compute_analytics
from agentops.triage import fleet_alerts, triage_all


def _span(name, trace_id, parent=None, status="OK", dur_ms=10.0, attrs=None):
    return {
        "name": name,
        "trace_id": trace_id,
        "span_id": name + trace_id[:4],
        "parent_span_id": parent,
        "start_ns": 0,
        "end_ns": int(dur_ms * 1_000_000),
        "duration_ms": dur_ms,
        "status": status,
        "status_message": None if status == "OK" else "boom",
        "service_name": "agentops-demo-agent",
        "attributes": attrs or {},
    }


def _root(trace_id, scenario, user="alice", dur_ms=10.0):
    return _span("agent.run research-assistant", trace_id, parent=None, status="UNSET",
                 dur_ms=dur_ms, attrs={"enduser.id": user, "agent.scenario": scenario})


def test_healthy_trace_no_incident():
    t = TraceSummary("aaaa1111", [
        _root("aaaa1111", "healthy"),
        _span("gen_ai.chat", "aaaa1111", parent="root", attrs={
            "gen_ai.request.model": "llama3.2:1b",
            "gen_ai.usage.cost_usd": 0.0001,
            "gen_ai.usage.output_tokens": 40}),
    ])
    assert triage_all([t]) == []


def test_error_trace_is_critical():
    t = TraceSummary("bbbb2222", [
        _root("bbbb2222", "tool_failure", user="bob"),
        _span("tool.web_search", "bbbb2222", status="ERROR",
              attrs={"tool.name": "web_search"}),
    ])
    reports = triage_all([t])
    assert reports and reports[0].severity == "CRITICAL"
    assert "web_search" in reports[0].root_cause


def test_cost_spike_detected():
    t = TraceSummary("cccc3333", [
        _root("cccc3333", "cost_spike", user="carol"),
        _span("gen_ai.chat", "cccc3333", attrs={
            "gen_ai.request.model": "llama3.2:1b",
            "gen_ai.usage.cost_usd": 0.02,
            "gen_ai.usage.output_tokens": 900}),
    ])
    reports = triage_all([t])
    assert any("Cost spike" in r.title for r in reports)


def test_latency_spike_detected():
    t = TraceSummary("dddd4444", [
        _root("dddd4444", "latency_spike", dur_ms=2500.0),
        _span("gen_ai.chat", "dddd4444", dur_ms=2400.0, attrs={
            "gen_ai.request.model": "llama3.2:3b",
            "gen_ai.usage.cost_usd": 0.0002}),
    ])
    reports = triage_all([t])
    assert any("Latency spike" in r.title for r in reports)


def test_analytics_and_fleet_alerts():
    traces = [
        TraceSummary("t1", [_root("t1", "healthy"),
                            _span("gen_ai.chat", "t1", attrs={
                                "gen_ai.request.model": "llama3.2:1b",
                                "gen_ai.usage.cost_usd": 0.001})]),
        TraceSummary("t2", [_root("t2", "tool_failure", user="bob"),
                            _span("tool.vector_db", "t2", status="ERROR",
                                  attrs={"tool.name": "vector_db"})]),
    ]
    a = compute_analytics(traces)
    assert a.total_traces == 2
    assert a.error_traces == 1
    assert a.error_rate == 0.5
    assert "llama3.2:1b" in a.cost_by_model
    assert any("ERROR-RATE" in x for x in fleet_alerts(a))
