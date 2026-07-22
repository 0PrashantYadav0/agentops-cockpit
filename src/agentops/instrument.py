"""AgentOps instrumentation core.

Sets up an OpenTelemetry tracer that fans out to two sinks:

* the **SigNoz** OTLP/HTTP endpoint (the real observability backend), and
* a **local JSONL ledger** (fallback + test surface).

It also exposes ergonomic context managers to record LLM calls and tool calls
using the OpenTelemetry **GenAI semantic conventions** (``gen_ai.*``), plus a
custom ``gen_ai.usage.cost_usd`` attribute so SigNoz can chart token spend.
"""
from __future__ import annotations

import contextlib
import os
from typing import Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from .cost import cost_for
from .ledger import DEFAULT_LEDGER, LedgerExporter

_SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "agentops-demo-agent")
_OTLP_ENDPOINT = os.environ.get(
    "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
)
_ENV = os.environ.get("DEPLOYMENT_ENVIRONMENT", "hackathon")

_initialised = False
_PROVIDER: TracerProvider | None = None


def setup_telemetry(
    service_name: str = _SERVICE_NAME,
    otlp_endpoint: str | None = _OTLP_ENDPOINT,
    ledger_path=DEFAULT_LEDGER,
    enable_otlp: bool = True,
) -> trace.Tracer:
    """Initialise the tracer provider (idempotent per process).

    We keep our own module-level provider instead of relying solely on OTel's
    global (which honours only the first ``set_tracer_provider`` call) so tests
    and repeated setups get a fresh, correctly-configured provider. Parent/child
    context still flows through OTel's contextvars, so tracing is unaffected.

    ``enable_otlp=False`` runs ledger-only (useful in tests / offline).
    """
    global _initialised, _PROVIDER
    if not _initialised or _PROVIDER is None:
        resource = Resource.create(
            {
                "service.name": service_name,
                "deployment.environment": _ENV,
            }
        )
        provider = TracerProvider(resource=resource)
        # Ledger export is synchronous so the data is on disk immediately.
        provider.add_span_processor(SimpleSpanProcessor(LedgerExporter(ledger_path)))

        if enable_otlp and otlp_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                traces_url = otlp_endpoint.rstrip("/") + "/v1/traces"
                provider.add_span_processor(
                    BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_url))
                )
            except Exception as exc:  # pragma: no cover - defensive
                print(f"[agentops] OTLP exporter disabled: {exc}")

        _PROVIDER = provider
        # Best-effort global set (first call wins); our module ref is source of truth.
        trace.set_tracer_provider(provider)
        _initialised = True
    return _PROVIDER.get_tracer("agentops")


def get_tracer() -> trace.Tracer:
    if _PROVIDER is None:
        return setup_telemetry()
    return _PROVIDER.get_tracer("agentops")


def flush() -> None:
    """Force-export any buffered spans (call before the process exits)."""
    if _PROVIDER is not None:
        _PROVIDER.force_flush()


@contextlib.contextmanager
def agent_run(name: str, user_id: str = "anonymous") -> Iterator[Span]:
    """Root span for one end-to-end agent invocation."""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        f"agent.run {name}", kind=SpanKind.SERVER
    ) as span:
        span.set_attribute("agent.name", name)
        span.set_attribute("enduser.id", user_id)
        yield span


@contextlib.contextmanager
def llm_call(
    model: str,
    prompt: str,
    user_id: str = "anonymous",
    system: str = "openai",
) -> Iterator[dict]:
    """Record one LLM call as a ``gen_ai`` span.

    Yields a mutable dict; set ``output_tokens``/``input_tokens``/``completion``
    on it inside the block and the span attributes + cost are filled in on exit.
    """
    tracer = get_tracer()
    holder: dict = {
        "input_tokens": max(1, len(prompt) // 4),
        "output_tokens": 0,
        "completion": "",
    }
    with tracer.start_as_current_span("gen_ai.chat", kind=SpanKind.CLIENT) as span:
        span.set_attribute("gen_ai.system", system)
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("enduser.id", user_id)
        try:
            yield holder
            breakdown = cost_for(
                model, holder["input_tokens"], holder["output_tokens"]
            )
            span.set_attribute("gen_ai.usage.input_tokens", breakdown.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", breakdown.output_tokens)
            span.set_attribute("gen_ai.usage.cost_usd", breakdown.total_usd)
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


@contextlib.contextmanager
def tool_call(tool_name: str, **attrs) -> Iterator[Span]:
    """Record one tool / retrieval invocation."""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        f"tool.{tool_name}", kind=SpanKind.INTERNAL
    ) as span:
        span.set_attribute("tool.name", tool_name)
        for k, v in attrs.items():
            span.set_attribute(f"tool.{k}", v)
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
