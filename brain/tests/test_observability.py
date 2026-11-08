"""Metrics from the timeline: counted by type and check, no ids or secrets in a label, readable only with the read scope."""

import httpx

from brain.api import Hub, create_app
from brain.config import ModelsConfig, PartnersConfig, Policy
from brain.contracts import TimelineEvent
from brain.observability import Metrics


def event(type, **data):
    return TimelineEvent(type=type, subject="sensor-secret-id", data=data)


def test_events_are_counted_by_type_and_a_held_action_by_its_check():
    metrics = Metrics()
    for e in (event("brain.reading.received"), event("brain.reading.received"), event("brain.action.blocked", check="evidence"), event("brain.decision.made")):
        metrics.write(e)
    text = metrics.render()

    assert 'brain_events_total{type="brain.reading.received"} 2' in text
    assert 'brain_gate_decisions_total{allowed="false",check="evidence"} 1' in text and 'brain_gate_decisions_total{allowed="true",check="passed"} 1' in text


def test_open_incidents_units_and_degraded_components_move_both_ways():
    metrics = Metrics()
    metrics.write(event("brain.incident.opened"))
    metrics.write(event("brain.action.result", status="dispatched"))
    metrics.write(event("brain.degraded", component="knowledge"))
    assert "brain_open_incidents 1" in metrics.render() and "brain_units_out 1" in metrics.render() and 'brain_degraded{component="knowledge"} 1' in metrics.render()
    metrics.write(event("brain.incident.closed"))
    metrics.write(event("brain.recovered", component="knowledge"))
    assert "brain_open_incidents 0" in metrics.render() and 'brain_degraded{component="knowledge"} 0' in metrics.render()


def test_no_id_or_secret_appears_in_a_metric_label():
    metrics = Metrics()
    metrics.write(event("brain.action.blocked", check="evidence", reason="token abc123 for sensor-secret-id"))

    assert "sensor-secret-id" not in metrics.render() and "abc123" not in metrics.render()


async def test_the_metrics_endpoint_requires_the_read_scope_off_loopback(monkeypatch, tmp_path):
    monkeypatch.setenv("BRAIN_TOKEN_READ", "read-token")
    hub = Hub(PartnersConfig.model_validate({"security": {"require": "always"}}), Policy(), ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}}), mocks="inproc", log_dir=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        assert (await client.get("/metrics")).status_code == 401
        ok = await client.get("/metrics", headers={"Authorization": "Bearer read-token"})

    assert ok.status_code == 200 and "# TYPE brain_events_total counter" in ok.text
