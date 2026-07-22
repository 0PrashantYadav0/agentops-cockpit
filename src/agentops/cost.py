"""Token cost model for AgentOps Cockpit.

Prices are USD per 1M tokens. Keep this table small and explicit (YAGNI): add
models only when you actually use them. Prices are illustrative hackathon-era
values -- swap in real numbers for production.
"""
from __future__ import annotations

from dataclasses import dataclass

# USD per 1,000,000 tokens: (input, output)
PRICING: dict[str, tuple[float, float]] = {
    # Real self-hosted models (Ollama). Rates are nominal $/1M tokens to amortise
    # local GPU/compute so cost telemetry stays meaningful for a local demo.
    "llama3.2:1b": (0.02, 0.04),
    "llama3.2:3b": (0.05, 0.10),
    "nomic-embed-text": (0.01, 0.00),
    # Hosted models kept for reference / easy switch-over.
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "claude-3-5-sonnet": (3.00, 15.00),
}
_FALLBACK = "llama3.2:1b"

_PER_TOKEN = 1_000_000


@dataclass(frozen=True)
class CostBreakdown:
    model: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float

    @property
    def total_usd(self) -> float:
        return round(self.input_cost_usd + self.output_cost_usd, 6)


def cost_for(model: str, input_tokens: int, output_tokens: int) -> CostBreakdown:
    """Compute the cost of a single LLM call.

    Unknown models fall back to the local model pricing rather than crashing --
    an observability tool must never take down the app it observes.
    """
    in_rate, out_rate = PRICING.get(model, PRICING[_FALLBACK])
    in_cost = round(input_tokens / _PER_TOKEN * in_rate, 6)
    out_cost = round(output_tokens / _PER_TOKEN * out_rate, 6)
    return CostBreakdown(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost_usd=in_cost,
        output_cost_usd=out_cost,
    )
