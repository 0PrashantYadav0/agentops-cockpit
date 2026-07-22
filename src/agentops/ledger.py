"""Local telemetry ledger.

A tiny OpenTelemetry ``SpanExporter`` that appends every finished span to a
JSONL file. This gives AgentOps two superpowers:

1. The Triage Copilot always has a queryable local copy of the telemetry, even
   if the SigNoz query API is temporarily unreachable (full-surety demos).
2. Tests can assert on emitted spans without standing up any backend.

Spans still go to SigNoz in parallel via the OTLP exporter -- the ledger is an
*additional* sink, not a replacement.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

DEFAULT_LEDGER = Path(
    os.environ.get("AGENTOPS_LEDGER", "./data/ledger.jsonl")
).expanduser()

_lock = threading.Lock()


def _span_to_dict(span: ReadableSpan) -> dict:
    ctx = span.get_span_context()
    parent = span.parent
    attrs = dict(span.attributes or {})
    start_ns = span.start_time or 0
    end_ns = span.end_time or 0
    return {
        "name": span.name,
        "trace_id": format(ctx.trace_id, "032x"),
        "span_id": format(ctx.span_id, "016x"),
        "parent_span_id": format(parent.span_id, "016x") if parent else None,
        "start_ns": start_ns,
        "end_ns": end_ns,
        "duration_ms": round((end_ns - start_ns) / 1_000_000, 3),
        "status": span.status.status_code.name if span.status else "UNSET",
        "status_message": (span.status.description if span.status else None),
        "service_name": (span.resource.attributes.get("service.name")
                         if span.resource else None),
        "attributes": attrs,
    }


class LedgerExporter(SpanExporter):
    """Append finished spans to a JSONL ledger file."""

    def __init__(self, path: Path | str = DEFAULT_LEDGER) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            with _lock, self.path.open("a", encoding="utf-8") as fh:
                for span in spans:
                    fh.write(json.dumps(_span_to_dict(span)) + "\n")
            return SpanExportResult.SUCCESS
        except Exception:  # never break the observed app
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:  # noqa: D401 - interface method
        return None


def read_ledger(path: Path | str = DEFAULT_LEDGER) -> list[dict]:
    """Load all spans from the ledger (oldest first)."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def clear_ledger(path: Path | str = DEFAULT_LEDGER) -> None:
    p = Path(path)
    if p.exists():
        p.unlink()
