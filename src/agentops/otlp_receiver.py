"""Minimal OTLP/HTTP trace receiver -- a stand-in for SigNoz's ingester.

Speaks the real OTLP protobuf protocol on ``/v1/traces`` (the same endpoint and
wire format SigNoz's collector exposes). Use it to PROVE that the AgentOps agent
truly exports OpenTelemetry over the network -- not just to the local ledger.

Run:   python -m agentops.otlp_receiver           # listens on :4318
Then:  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
       python -m agentops.run_demo --runs 8
It prints every received span with its gen_ai / cost / tool attributes and a
running total, then a summary on Ctrl-C.
"""
from __future__ import annotations

import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

_span_count = 0
_name_counts: Counter = Counter()
_cost_total = 0.0


def _attr_value(v) -> object:
    if v.HasField("string_value"):
        return v.string_value
    if v.HasField("int_value"):
        return v.int_value
    if v.HasField("double_value"):
        return round(v.double_value, 6)
    if v.HasField("bool_value"):
        return v.bool_value
    return None


class OTLPHandler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silence default access logs
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        global _span_count, _cost_total
        if not self.path.endswith("/v1/traces"):
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        req = trace_service_pb2.ExportTraceServiceRequest()
        req.ParseFromString(body)

        for rs in req.resource_spans:
            svc = next(
                (
                    _attr_value(a.value)
                    for a in rs.resource.attributes
                    if a.key == "service.name"
                ),
                "?",
            )
            for ss in rs.scope_spans:
                for span in ss.spans:
                    _span_count += 1
                    _name_counts[span.name] += 1
                    attrs = {a.key: _attr_value(a.value) for a in span.attributes}
                    cost = attrs.get("gen_ai.usage.cost_usd")
                    if isinstance(cost, (int, float)):
                        _cost_total += float(cost)
                    extras = []
                    if "gen_ai.request.model" in attrs:
                        extras.append(f"model={attrs['gen_ai.request.model']}")
                    if cost is not None:
                        extras.append(f"cost=${cost}")
                    if "tool.name" in attrs:
                        extras.append(f"tool={attrs['tool.name']}")
                    status = span.status.code  # 0 UNSET,1 OK,2 ERROR
                    tag = {0: "UNSET", 1: "OK", 2: "ERROR"}.get(status, "?")
                    print(
                        f"[recv #{_span_count:>3}] svc={svc} span={span.name} "
                        f"status={tag} {' '.join(extras)}"
                    )

        # OTLP success response (empty ExportTraceServiceResponse)
        resp = trace_service_pb2.ExportTraceServiceResponse().SerializeToString()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)


def main() -> None:
    ap = argparse.ArgumentParser(description="Minimal OTLP/HTTP trace receiver")
    ap.add_argument("--port", type=int, default=4318)
    args = ap.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), OTLPHandler)
    print(f"[otlp-receiver] listening on http://0.0.0.0:{args.port}/v1/traces")
    print("[otlp-receiver] point OTEL_EXPORTER_OTLP_ENDPOINT here, Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n" + "=" * 60)
        print("[otlp-receiver] SUMMARY")
        print(f"  spans received over OTLP : {_span_count}")
        print(f"  span types               : {dict(_name_counts)}")
        print(f"  total gen_ai cost seen   : ${round(_cost_total, 6)}")
        print("=" * 60)


if __name__ == "__main__":
    main()
