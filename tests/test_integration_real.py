"""Real integration test -- runs the agent against the REAL Ollama LLM.

Skipped automatically if Ollama isn't reachable, so `pytest` stays green in any
environment. When Ollama is up, this exercises the full real path:
real LLM + real embeddings + real Wikipedia + OTel instrumentation -> ledger.
"""
import importlib

import pytest

import agentops.instrument as instrument
from agentops import agent as agent_mod
from agentops import llm_client
from agentops.ledger import read_ledger
from agentops.telemetry_store import load_traces
from agentops.triage import triage_all

pytestmark = pytest.mark.skipif(
    not llm_client.is_up(), reason="Ollama not running (start `ollama serve`)"
)


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(instrument, "_initialised", False)
    monkeypatch.setattr(instrument, "_PROVIDER", None)
    instrument.setup_telemetry(enable_otlp=False, ledger_path=path)
    return path


def test_real_healthy_run_emits_spans(ledger):
    agent_mod.run_agent("What is OpenTelemetry?", user_id="alice",
                        scenario=agent_mod.SCENARIOS["healthy"])
    instrument.flush()
    spans = read_ledger(ledger)
    names = {s["name"] for s in spans}
    assert "agent.run research-assistant" in names
    assert "gen_ai.chat" in names
    assert "tool.web_search" in names
    assert "tool.vector_db" in names
    gen = [s for s in spans if s["name"] == "gen_ai.chat"]
    # real token accounting from the model server
    assert all(s["attributes"].get("gen_ai.usage.output_tokens", 0) > 0 for s in gen)


def test_real_llm_outage_is_critical(ledger):
    with pytest.raises(Exception):
        agent_mod.run_agent("anything", user_id="dave",
                            scenario=agent_mod.SCENARIOS["llm_outage"])
    instrument.flush()
    reports = triage_all(load_traces(ledger))
    assert reports and reports[0].severity == "CRITICAL"
