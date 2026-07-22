"""Real agent tools -- no mocks.

* ``web_search`` uses the live Wikipedia search API, then fetches the best page
  summary via the REST API.
* ``vector_db`` does real retrieval: embed a small corpus with Ollama's
  nomic-embed-text model and rank by cosine similarity.
* ``calculator`` evaluates sanitised arithmetic.

Each raises a real exception on failure so the surrounding span is ERROR.
"""
from __future__ import annotations

import math
import time

import httpx

from .llm_client import embed

WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
WIKI_SEARCH = "https://en.wikipedia.org/w/api.php"
_HEADERS = {"User-Agent": "AgentOps-Cockpit/0.1"}

# a tiny real knowledge corpus for the vector-DB tool
CORPUS = [
    "SigNoz is an open-source OpenTelemetry-native observability platform for traces, metrics, and logs.",
    "OpenTelemetry is a vendor-neutral standard for generating and collecting telemetry data.",
    "A span represents a single unit of work; a trace is a tree of spans across a request.",
    "The OTLP protocol exports telemetry over gRPC (4317) or HTTP (4318) to a collector.",
    "LLM cost is driven by input and output token counts multiplied by per-model rates.",
    "The SigNoz Query Builder aggregates traces and logs with group-by, having, and order-by.",
    "GPU saturation and queue depth are common causes of self-hosted inference latency.",
    "Auto-instrumentation emits spans for a framework without manual code changes.",
]

_corpus_vecs: list[list[float]] | None = None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def web_search(query: str, title: str | None = None, timeout: float = 10.0) -> list[str]:
    """Real web search: Wikipedia search API -> best page -> REST summary.

    If ``title`` is given it is fetched directly (used to force a real 404 in the
    tool-failure scenario).
    """
    if title is None:
        sr = httpx.get(WIKI_SEARCH, timeout=timeout, headers=_HEADERS, params={
            "action": "query", "list": "search", "srsearch": query,
            "format": "json", "srlimit": 1,
        })
        if sr.status_code == 429:
            time.sleep(2.0)
            sr = httpx.get(WIKI_SEARCH, timeout=timeout, headers=_HEADERS, params={
                "action": "query", "list": "search", "srsearch": query,
                "format": "json", "srlimit": 1,
            })
        if sr.status_code != 200:
            raise RuntimeError(f"web_search API failed: HTTP {sr.status_code}")
        results = sr.json().get("query", {}).get("search", [])
        if not results:
            raise RuntimeError(f"web_search: no results for '{query}'")
        title = results[0]["title"]
    topic = title.strip().replace(" ", "_")
    r = httpx.get(WIKI_SUMMARY + topic, timeout=timeout, follow_redirects=True,
                  headers=_HEADERS)
    if r.status_code != 200:
        raise RuntimeError(f"web_search failed for '{topic}': HTTP {r.status_code}")
    extract = r.json().get("extract", "")
    if not extract:
        raise RuntimeError(f"web_search: no content for '{topic}'")
    return [extract]


def vector_db(query: str, top_k: int = 3, embed_model: str = "nomic-embed-text") -> list[str]:
    """Real semantic retrieval: embed query + corpus, rank by cosine similarity."""
    global _corpus_vecs
    if _corpus_vecs is None:
        _corpus_vecs = [embed(doc, model=embed_model) for doc in CORPUS]
    qv = embed(query, model=embed_model)
    scored = sorted(
        zip(CORPUS, _corpus_vecs), key=lambda p: _cosine(qv, p[1]), reverse=True
    )
    return [doc for doc, _ in scored[:top_k]]


def calculator(expression: str) -> float:
    allowed = set("0123456789+-*/(). ")
    if not set(expression) <= allowed:
        raise ValueError(f"unsafe expression rejected: {expression!r}")
    return eval(expression)  # noqa: S307 - sanitised above
