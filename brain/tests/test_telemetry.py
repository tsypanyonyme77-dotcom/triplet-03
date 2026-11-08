"""Spans from the timeline: one span per event, one trace per reading, nothing secret, and a dead collector costs nothing."""

import logging
import time

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace.export import SpanExporter  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

from brain.api import Broadcaster  # noqa: E402
from brain.config import ModelsConfig  # noqa: E402
from brain.contracts import TimelineEvent  # noqa: E402
from brain.scenario import inproc_partners, load_scenario, run_scenario  # noqa: E402
from brain.telemetry import SpanSink, trace_id_for  # noqa: E402


def event(type, trace=None, **data):
    return TimelineEvent(type=type, subject="cam-07-02", traceid=trace, data=data)


def sink_with_memory():
    memory = InMemorySpanExporter()
    return SpanSink.with_exporter(memory, batch=False), memory


def test_every_event_becomes_one_span_with_its_type_as_the_name():
    sink, memory = sink_with_memory()
    for kind in ("brain.reading.received", "brain.verdict.received", "brain.decision.made"):
        sink.write(event(kind, "cam-07-02:1"))

    assert [s.name for s in memory.get_finished_spans()] == ["brain.reading.received", "brain.verdict.received", "brain.decision.made"]


def test_events_of_one_reading_share_a_trace_id_and_another_reading_has_its_own():
    sink, memory = sink_with_memory()
    sink.write(event("brain.reading.received", "cam-07-02:1"))
    sink.write(event("brain.decision.made", "cam-07-02:1"))
    sink.write(event("brain.reading.received", "cam-07-02:2"))
    first, second, other = memory.get_finished_spans()

    assert first.context.trace_id == second.context.trace_id == trace_id_for("cam-07-02:1")
    assert other.context.trace_id != first.context.trace_id


def test_the_trace_id_is_the_same_in_every_run():
    assert trace_id_for("cam-07-02:1") == trace_id_for("cam-07-02:1") and trace_id_for("a") != trace_id_for("b")


def test_a_held_action_says_which_check_held_it_and_that_it_was_not_allowed():
    sink, memory = sink_with_memory()
    sink.write(event("brain.action.blocked", "cam-07-02:1", check="evidence", reason="not enough witnesses"))
    attributes = memory.get_finished_spans()[0].attributes

    assert attributes["brain.gate.check"] == "evidence" and attributes["brain.gate.allowed"] is False


def test_no_token_secret_or_reading_value_appears_in_a_span():
    sink, memory = sink_with_memory()
    sink.write(event("brain.reading.received", "cam-07-02:1", token="s3cret-token", value={"plate": "123 TUN 4567"}, hmac="abcdef", check="evidence"))
    text = repr(dict(memory.get_finished_spans()[0].attributes))

    assert "s3cret" not in text and "TUN" not in text and "abcdef" not in text


def test_a_span_uses_the_events_time_and_its_measured_duration():
    sink, memory = sink_with_memory()
    e = event("brain.solver.solved", "inc-1")
    e.timing = {"elapsed_ms": 40.0}
    sink.write(e)
    span = memory.get_finished_spans()[0]

    assert span.start_time == int(e.time.timestamp() * 1e9) and span.end_time - span.start_time == 40_000_000


class DeadCollector(SpanExporter):
    def __init__(self, slow_s: float = 0.0):
        self.calls, self.slow_s = 0, slow_s

    def export(self, spans):
        self.calls += 1
        time.sleep(self.slow_s)
        raise ConnectionRefusedError("collector is down")


def test_a_dead_collector_does_not_slow_or_stop_the_brain_and_reports_once(caplog):
    collector = DeadCollector(slow_s=0.2)
    sink = SpanSink.with_exporter(collector, batch=True)
    caplog.set_level(logging.WARNING, logger="brain.telemetry")

    started = time.perf_counter()
    for n in range(500):
        sink.write(event("brain.reading.received", f"cam:{n}"))
    writing = time.perf_counter() - started
    sink.shutdown()

    assert writing < 1.0  # the collector sleeps 0.2 s per batch; writing never waits for it
    assert len([r for r in caplog.records if "span collector" in r.message]) == 1


async def test_the_broadcaster_keeps_working_when_the_span_sink_breaks():
    class Broken:
        def write(self, event):
            raise RuntimeError("boom")

    broadcaster = Broadcaster(spans=Broken())
    broadcaster.write(event("brain.reading.received"))
    broadcaster.write(event("brain.reading.received"))

    assert len(broadcaster.buffer) == 2 and broadcaster.spans is None


async def test_a_scenario_run_makes_spans_whose_traces_follow_each_reading():
    sink, memory = sink_with_memory()
    broadcaster = Broadcaster(spans=sink)
    models = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})

    result = await run_scenario(load_scenario("t14"), inproc_partners(), models=models, speed=0, timeout_s=30, extra_sinks=[broadcaster])

    spans = memory.get_finished_spans()
    assert result.passed and len(spans) == len(result.sink.events)
    decision = next(s for s in spans if s.name == "brain.decision.made")
    received = [s for s in spans if s.name == "brain.reading.received" and s.context.trace_id == decision.context.trace_id]
    assert received  # the decision sits in the trace of the reading that caused it
