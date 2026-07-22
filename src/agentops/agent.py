"""Demo research agent -- real services, fully instrumented with AgentOps.

Chain: plan (real LLM) -> web_search (real Wikipedia) -> vector_db (real
embeddings retrieval) -> synthesise (real LLM). Each step is a span; the whole
run is one trace exported to SigNoz.

Scenarios trigger REAL failures/anomalies (no simulation):
- llm_outage    : call a non-existent model -> real provider error
- cost_spike    : ask for a long synthesis with a high token budget -> real high output tokens
- latency_spike : synthesise with the bigger llama3.2:3b model -> real higher latency
- tool_failure  : query a Wikipedia title that 404s -> real HTTP error
- vector_failure: embed with a non-existent model -> real embedding error
"""
from __future__ import annotations

from dataclasses import dataclass

from . import llm_client, tools_real
from .instrument import agent_run, llm_call, tool_call


@dataclass
class Scenario:
    name: str = "healthy"
    model: str = llm_client.DEFAULT_MODEL
    synth_model: str = llm_client.DEFAULT_MODEL
    synth_max_tokens: int = 160
    bad_wiki_title: str | None = None
    embed_model: str = "nomic-embed-text"


SCENARIOS: dict[str, Scenario] = {
    "healthy": Scenario("healthy"),
    "cost_spike": Scenario("cost_spike", synth_max_tokens=900),
    "latency_spike": Scenario("latency_spike", synth_model=llm_client.BIG_MODEL,
                              synth_max_tokens=400),
    "tool_failure": Scenario("tool_failure",
                             bad_wiki_title="ThisPageDefinitelyDoesNotExist_XYZ123"),
    "vector_failure": Scenario("vector_failure", embed_model="no-such-embed-model"),
    "llm_outage": Scenario("llm_outage", model="no-such-model:999"),
}


def run_agent(question: str, user_id: str = "anonymous", scenario: Scenario | None = None) -> str:
    """Run one research task end to end against REAL services. Raises on failure."""
    sc = scenario or SCENARIOS["healthy"]
    with agent_run("research-assistant", user_id=user_id) as root:
        root.set_attribute("agent.question", question)
        root.set_attribute("agent.scenario", sc.name)

        # Step 1: plan (real LLM)
        with llm_call(sc.model, f"Plan research for: {question}", user_id=user_id,
                      system="ollama") as call:
            out = llm_client.chat(f"In one sentence, how would you research: {question}",
                                  model=sc.model, max_tokens=80)
            call["input_tokens"] = out["input_tokens"]
            call["output_tokens"] = out["output_tokens"]
            plan = out["completion"]

        # Step 2: web search (real Wikipedia)
        with tool_call("web_search", query=question):
            hits = tools_real.web_search(question, title=sc.bad_wiki_title)

        # Step 3: vector retrieval (real embeddings)
        with tool_call("vector_db", query=question):
            docs = tools_real.vector_db(question, embed_model=sc.embed_model)

        # Step 4: synthesise (real LLM, can overspend / be slow)
        context = f"PLAN:{plan}\nWEB:{hits[0][:400]}\nDOCS:{docs}"
        prompt = (
            f"Answer the question '{question}' using this context. "
            + ("Write a long, detailed, multi-paragraph explanation. " if sc.name == "cost_spike" else "")
            + f"\n\n{context}"
        )
        with llm_call(sc.synth_model, prompt, user_id=user_id, system="ollama") as call:
            out = llm_client.chat(prompt, model=sc.synth_model,
                                  max_tokens=sc.synth_max_tokens)
            call["input_tokens"] = out["input_tokens"]
            call["output_tokens"] = out["output_tokens"]
            answer = out["completion"]

        root.set_attribute("agent.answer_preview", answer[:80])
        return answer
