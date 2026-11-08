"""OpenTelemetry spans from the timeline: one span per event, one trace per reading.

A sink on the same stream that feeds the screen and the metrics. Each timeline event becomes a span named by its type. Events that share a
`traceid` (the reading that caused them) share an OpenTelemetry trace, so a tracing UI shows one reading's whole path: perception, verdict,
decision, gate, actuator. An event with no `traceid` gets a trace of its own.

What a span carries is a short allow-list (subject, department, the gate check, whether the action was allowed), never the event's `data`:
a span is sent to a collector, and nothing that could hold a token or a reading's value goes with it. Timing comes from the event's `time`
and its measured `timing`, not from when the sink ran, so a replayed log draws the same picture.

The exporter is optional (`uv sync --extra otel`) and never in the Brain's way: spans are batched and sent from a background thread, a full
queue drops spans, and a collector that is down is reported once and then ignored.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from brain.contracts import TimelineEvent

log = logging.getLogger("brain.telemetry")

# What a span may say about an event: nothing from `data` except these, and only as plain values.
SPAN_DATA_KEYS = {"check": "brain.gate.check", "allowed": "brain.gate.allowed", "department": "brain.department", "status": "brain.status", "component": "brain.component"}


def trace_id_for(key: str) -> int:
    """16 bytes from a hash of the reading's trace key: the same reading is the same trace in every run and on every machine."""
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:16], "big") or 1


def span_id_for(key: str) -> int:
    return int.from_bytes(hashlib.sha256(b"root:" + key.encode()).digest()[:8], "big") or 1


def _plain(value: Any) -> str | bool | int | float | None:
    if isinstance(value, bool | int | float):
        return value
    return str(value)[:120] if isinstance(value, str) else None


class SpanSink:
    """A `TimelineSink` that turns events into spans on its own tracer provider (never the process-wide one)."""

    def __init__(self, provider: Any, service_name: str = "city-brain") -> None:
        from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context

        self._provider = provider
        self._tracer = provider.get_tracer(service_name)
        self._root = lambda key: set_span_in_context(NonRecordingSpan(SpanContext(trace_id_for(key), span_id_for(key), is_remote=True, trace_flags=TraceFlags(TraceFlags.SAMPLED))))
        self.spans = 0

    @classmethod
    def with_exporter(cls, exporter: Any, service_name: str = "city-brain", batch: bool = True) -> SpanSink:
        """`batch=False` exports each span as it ends (for tests); the default queues and sends from a background thread."""
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor((BatchSpanProcessor if batch else SimpleSpanProcessor)(GuardedExporter(exporter)))
        return cls(provider, service_name)

    @classmethod
    def from_endpoint(cls, endpoint: str, service_name: str = "city-brain") -> SpanSink | None:
        """Spans to an OTLP/HTTP collector, or None (with one warning) when the optional packages are not installed."""
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError:
            log.warning("otlp_endpoint is set but the OpenTelemetry packages are not installed (uv sync --extra otel): no spans will be sent")
            return None
        return cls.with_exporter(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces", timeout=3), service_name)

    def write(self, event: TimelineEvent) -> None:
        key = event.traceid or event.id
        attributes: dict[str, Any] = {"brain.event.id": event.id, "brain.source": event.source}
        if event.subject:
            attributes["brain.subject"] = event.subject[:120]
        for name, attribute in SPAN_DATA_KEYS.items():
            value = _plain(event.data.get(name)) if event.data else None
            if value is not None:
                attributes[attribute] = value
        if event.type == "brain.decision.made":
            attributes["brain.gate.allowed"] = True
        elif event.type == "brain.action.blocked":
            attributes["brain.gate.allowed"] = False
        start = int(event.time.timestamp() * 1e9)
        elapsed_ms = (event.timing or {}).get("elapsed_ms", 0.0)
        span = self._tracer.start_span(event.type, context=self._root(key), start_time=start, attributes=attributes)
        span.end(end_time=start + int(elapsed_ms * 1e6))
        self.spans += 1

    def shutdown(self) -> None:
        self._provider.shutdown()


def GuardedExporter(inner: Any) -> Any:  # noqa: N802  a class built on first use, so importing this module needs no OpenTelemetry
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    class _Guarded(SpanExporter):
        """Passes spans to `inner`; when it fails, says so once and reports failure quietly instead of raising on every batch."""

        def __init__(self) -> None:
            self.inner, self.failed, self.reported = inner, False, False

        def export(self, spans: Any) -> Any:
            reason = ""
            try:
                result = self.inner.export(spans)
                if result == SpanExportResult.SUCCESS:
                    return result
                reason = "it refused them"  # the OTLP exporter reports a collector that is down this way, after its own retries
            except Exception as error:  # a refused connection, a bad certificate  # noqa: BLE001
                reason = type(error).__name__
            self.failed = True
            if not self.reported:
                self.reported = True
                log.warning("the span collector did not take the spans (%s); the Brain carries on and will not say so again", reason)
            return SpanExportResult.FAILURE

        def shutdown(self) -> None:
            try:
                self.inner.shutdown()
            except Exception:  # noqa: BLE001 - shutting down a collector must never raise
                pass

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    return _Guarded()
