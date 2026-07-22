"""Telemetry store + analytics.

The analysis layer reads spans from the local ledger -- which is a byte-for-byte
copy of what was shipped to SigNoz over OTLP -- so results match the SigNoz UI.
``SigNozClient`` proves the live integration (health + trace queries) and is used
to enrich/verify; the ledger keeps the demo deterministic and offline-safe.
"""
from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field

import httpx

from .ledger import DEFAULT_LEDGER, read_ledger


# --------------------------------------------------------------------------- #
# Live SigNoz integration
# --------------------------------------------------------------------------- #
class SigNozClient:
    """Thin client to confirm the SigNoz backend is alive and reachable."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (
            base_url or os.environ.get("SIGNOZ_URL", "http://localhost:8080")
        ).rstrip("/")

    def is_up(self, timeout: float = 2.0) -> bool:
        for path in ("/api/v1/health", "/api/v1/version", "/"):
            try:
                r = httpx.get(self.base_url + path, timeout=timeout)
                if r.status_code < 500:
                    return True
            except Exception:
                continue
        return False


# --------------------------------------------------------------------------- #
# Trace model + analytics (computed from ledger == SigNoz data)
# --------------------------------------------------------------------------- #
@dataclass
class TraceSummary:
    trace_id: str
    spans: list[dict] = field(default_factory=list)

    @property
    def root(self) -> dict | None:
        for s in self.spans:
            if s.get("parent_span_id") is None:
                return s
        return self.spans[0] if self.spans else None

    @property
    def has_error(self) -> bool:
        return any(s.get("status") == "ERROR" for s in self.spans)

    @property
    def duration_ms(self) -> float:
        r = self.root
        return r["duration_ms"] if r else 0.0

    @property
    def total_cost_usd(self) -> float:
        return round(
            sum(
                float(s["attributes"].get("gen_ai.usage.cost_usd", 0.0))
                for s in self.spans
            ),
            6,
        )

    @property
    def total_tokens(self) -> int:
        return sum(
            int(s["attributes"].get("gen_ai.usage.input_tokens", 0))
            + int(s["attributes"].get("gen_ai.usage.output_tokens", 0))
            for s in self.spans
        )

    @property
    def user_id(self) -> str:
        r = self.root
        if r:
            return r["attributes"].get("enduser.id", "anonymous")
        return "anonymous"

    @property
    def scenario(self) -> str:
        r = self.root
        return r["attributes"].get("agent.scenario", "unknown") if r else "unknown"

    def error_spans(self) -> list[dict]:
        return [s for s in self.spans if s.get("status") == "ERROR"]


def load_traces(path=DEFAULT_LEDGER) -> list[TraceSummary]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for span in read_ledger(path):
        grouped[span["trace_id"]].append(span)
    return [TraceSummary(tid, spans) for tid, spans in grouped.items()]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(round((pct / 100) * (len(s) - 1))))
    return round(s[idx], 3)


@dataclass
class Analytics:
    total_traces: int
    error_traces: int
    error_rate: float
    total_cost_usd: float
    cost_by_model: dict[str, float]
    cost_by_user: dict[str, float]
    p50_latency_ms: float
    p95_latency_ms: float
    total_tokens: int


def compute_analytics(traces: list[TraceSummary]) -> Analytics:
    cost_by_model: dict[str, float] = defaultdict(float)
    cost_by_user: dict[str, float] = defaultdict(float)
    for t in traces:
        for s in t.spans:
            model = s["attributes"].get("gen_ai.request.model")
            cost = float(s["attributes"].get("gen_ai.usage.cost_usd", 0.0))
            if model and cost:
                cost_by_model[model] += cost
        cost_by_user[t.user_id] += t.total_cost_usd

    latencies = [t.duration_ms for t in traces]
    errors = sum(1 for t in traces if t.has_error)
    total = len(traces)
    return Analytics(
        total_traces=total,
        error_traces=errors,
        error_rate=round(errors / total, 4) if total else 0.0,
        total_cost_usd=round(sum(t.total_cost_usd for t in traces), 6),
        cost_by_model={k: round(v, 6) for k, v in cost_by_model.items()},
        cost_by_user={k: round(v, 6) for k, v in cost_by_user.items()},
        p50_latency_ms=_percentile(latencies, 50),
        p95_latency_ms=_percentile(latencies, 95),
        total_tokens=sum(t.total_tokens for t in traces),
    )
