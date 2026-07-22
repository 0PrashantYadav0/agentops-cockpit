"""Real LLM client -- talks to a local Ollama inference server.

This is a genuine model service (Llama 3.2 running on Ollama), not a mock. It
returns the *real* prompt/eval token counts Ollama reports, which the
instrumentation turns into real cost + latency telemetry in SigNoz.

Ollama is OpenAI-shaped and needs no API key. Start it with `ollama serve`
and `ollama pull llama3.2:1b`.
"""
from __future__ import annotations

import os

import httpx

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("AGENTOPS_MODEL", "llama3.2:1b")
BIG_MODEL = os.environ.get("AGENTOPS_BIG_MODEL", "llama3.2:3b")


class LLMError(RuntimeError):
    """Raised when the real model service returns an error."""


def chat(
    prompt: str,
    model: str = DEFAULT_MODEL,
    system: str = "You are a concise, helpful research assistant.",
    max_tokens: int = 200,
    timeout: float = 120.0,
) -> dict:
    """Call the real Ollama chat API. Returns completion + real token counts.

    Raises ``LLMError`` on any provider failure (non-200, unknown model, etc.) so
    the caller's span is marked ERROR -- exactly what we want to observe.
    """
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"num_predict": max_tokens},
    }
    try:
        r = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=timeout)
    except Exception as exc:  # network/connection failure = real outage
        raise LLMError(f"LLM transport error calling {model}: {exc}") from exc
    if r.status_code != 200:
        raise LLMError(f"LLM provider returned {r.status_code}: {r.text[:160]}")
    data = r.json()
    if "error" in data:
        raise LLMError(f"LLM provider error: {data['error']}")
    msg = data.get("message", {}).get("content", "")
    return {
        "completion": msg,
        "model": model,
        # real token accounting from the model server
        "input_tokens": int(data.get("prompt_eval_count", max(1, len(prompt) // 4))),
        "output_tokens": int(data.get("eval_count", max(1, len(msg) // 4))),
    }


def embed(text: str, model: str = "nomic-embed-text", timeout: float = 60.0) -> list[float]:
    """Real embedding via Ollama (used by the vector-DB retrieval tool)."""
    try:
        r = httpx.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=timeout,
        )
    except Exception as exc:
        raise LLMError(f"embedding transport error ({model}): {exc}") from exc
    if r.status_code != 200:
        raise LLMError(f"embedding provider returned {r.status_code}: {r.text[:160]}")
    emb = r.json().get("embedding")
    if not emb:
        raise LLMError("embedding provider returned empty vector")
    return emb


def is_up(timeout: float = 2.0) -> bool:
    try:
        return httpx.get(f"{OLLAMA_URL}/api/version", timeout=timeout).status_code == 200
    except Exception:
        return False
