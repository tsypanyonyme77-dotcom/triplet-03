"""The Guardian team's contract 1.0: our adapter against payloads taken from their Interface Card and from their running Guardian."""
import json
from pathlib import Path

import httpx
import pytest

from brain.adapters.guardian_v1 import GuardianGateway, GuardianV1Adapter, from_guardian_answer, sign, to_guardian_call, to_verdict
from brain.contracts import ActuatorCall, ActuatorResult
from brain.ports import GuardianUnavailable, TwinError

VERDICT = json.loads((Path(__file__).parent / "data/guardian_v1_verdict.json").read_text())  # their example, signed with `example-guardian-key`
KEY = "example-guardian-key"
READING = {"sensor_id": "wl-port-03", "sequence_no": 4821}


def adapter(handler, **kw) -> GuardianV1Adapter:
    return GuardianV1Adapter("http://guardian", httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://guardian"), **{"api_key": "k", "hmac_secret": KEY, "poll_s": 0.01, **kw})


def signed(**changes) -> dict:
    body = {k: v for k, v in {**VERDICT, **changes}.items() if k != "signature"}
    return {**body, "signature": sign(body, KEY)}


def test_our_signature_matches_the_one_in_their_interface_card():
    assert sign({k: v for k, v in VERDICT.items() if k != "signature"}, KEY) == VERDICT["signature"]


def test_their_verdict_becomes_ours_and_keeps_what_ours_does_not_have():
    verdict = to_verdict(VERDICT)

    assert verdict.status == "untrusted" and verdict.confidence == 0.2 and verdict.issued_at.isoformat().startswith("2026-11-02T14:03:23")
    assert verdict.reading_ref.sensor_id == "wl-port-03" and verdict.model_extra["threat_level"] == "normal" and verdict.model_extra["layer_results"]
    assert to_verdict({**VERDICT, "status": "suspect"}).status == "suspicious"


async def test_a_verdict_is_asked_for_by_sensor_and_sequence_with_our_api_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(path=request.url.path, key=request.headers["x-api-key"], body=json.loads(request.content))
        return httpx.Response(200, json=signed())

    verdict = await adapter(handler).get_verdict({**READING, "type": "water_level"}, 1.0)

    assert seen == {"path": "/v1/verdicts/request", "key": "k", "body": READING} and verdict.verdict_id == "verdict-88213"


async def test_a_reading_the_twin_has_not_pushed_yet_is_asked_about_again_until_it_arrives():
    answers = [signed(status="unknown", reasons=["unknown_sensor"]), signed(status="unknown", reasons=["unknown_sensor"]), signed(status="trusted")]

    verdict = await adapter(lambda request: httpx.Response(200, json=answers.pop(0))).get_verdict(READING, 1.0)

    assert verdict.status == "trusted" and not answers


async def test_a_verdict_that_never_leaves_unknown_is_no_verdict():
    with pytest.raises(GuardianUnavailable, match="unknown_sensor"):
        await adapter(lambda request: httpx.Response(200, json=signed(status="unknown", reasons=["unknown_sensor"]))).get_verdict(READING, 0.1)


async def test_a_verdict_with_the_wrong_signature_is_not_used():
    forged = {**signed(), "status": "trusted"}

    with pytest.raises(GuardianUnavailable, match="signature"):
        await adapter(lambda request: httpx.Response(200, json=forged)).get_verdict(READING, 0.5)


async def test_a_guardian_that_is_down_raises_unavailable():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(GuardianUnavailable):
        await adapter(down).get_verdict(READING, 0.5)


async def test_a_device_is_quarantined_when_the_containment_list_names_it():
    handler = lambda request: httpx.Response(200, json={"active": [{"device_id": "valve-res-02", "kind": "quarantine"}]})  # noqa: E731

    assert await adapter(handler).is_quarantined("valve-res-02") and not await adapter(handler).is_quarantined("valve-port-12")


def call(action: str, params: dict, actuator="valve-port-12") -> ActuatorCall:
    return ActuatorCall(actuator_id=actuator, action=action, params=params, justification="flood risk", trust_ref="verdict-1")


def test_our_actions_are_sent_under_their_names():
    valve = to_guardian_call(call("set_valve_state", {"valve_id": "valve-port-12", "state": "closed"}))
    grid = to_guardian_call(call("set_grid_connection", {"zone_id": "zone-07", "state": "disconnected"}, "grid-port"))
    signal = to_guardian_call(call("set_signal_phase", {"intersection_id": "i-1", "phase": "red", "duration_s": 60}, "sig-port-01"))
    unit = to_guardian_call(call("dispatch_unit", {"unit_type": "fire", "zone_id": "zone-07", "incident_id": "inc-1", "mode": "respond"}, "fire-1"))

    assert (valve["action"], valve["params"]) == ("set_valve_state", {"state": "closed"})
    assert (grid["action"], grid["params"], grid["zone_id"]) == ("set_grid_state", {"state": "disconnected"}, "zone-07")
    assert (signal["action"], signal["params"]) == ("set_signal", {"state": "red", "duration_s": 60})
    assert unit["params"] == {"unit_type": "fire", "mode": "respond"} and unit["incident_id"] == "inc-1"
    central = to_guardian_call(call("dispatch_unit", {"unit_type": "fire", "zone_id": "zone-07", "incident_id": "inc-1"}, "fire-dispatch-04"), "dispatch-central")
    assert central["actuator_id"] == "dispatch-central" and central["params"]["station_id"] == "fire-dispatch-04" and unit["actuator_id"] == "fire-1"
    assert valve["requesting_layer"] == "brain" and valve["trust_ref"] == "verdict-1" and valve["call_id"].startswith("call-")
    assert to_guardian_call(call("set_valve_state", {"valve_id": "v", "state": "open"}))["call_id"] == to_guardian_call(call("set_valve_state", {"valve_id": "v", "state": "open"}))["call_id"]


def test_their_answer_becomes_our_result_and_a_block_keeps_its_reasons():
    valve = call("set_valve_state", {"valve_id": "valve-port-12", "state": "closed"})
    ok = from_guardian_answer(valve, {"call_id": "c", "decision": "forwarded", "reasons": [], "twin_reply": {"status": "ok", "current_state": {"state": "closed"}}})
    blocked = from_guardian_answer(valve, {"call_id": "c", "decision": "blocked", "reasons": ["trust_ref_not_trusted", "sensor_isolated"]})

    assert ok.status == "set" and ok.model_extra["current_state"] == {"state": "closed"}
    assert blocked.status == "rejected" and blocked.reason == "trust_ref_not_trusted, sensor_isolated"
    assert from_guardian_answer(call("dispatch_unit", {"unit_type": "fire", "zone_id": "z", "incident_id": "i"}), {"decision": "forwarded", "twin_reply": {"status": "ok", "current_state": {"unit_id": "fire-1"}}}).model_extra["unit_id"] == "fire-1"


class FakeTwin:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_actuator(self, c: ActuatorCall) -> ActuatorResult:
        self.calls.append(c.action)
        return ActuatorResult(status="broadcast")

    async def get_topology(self) -> dict:
        return {"zones": []}


async def test_the_gateway_sends_audited_actions_through_the_guardian_and_the_rest_to_the_twin():
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["action"])
        return httpx.Response(200, json={"call_id": "c", "decision": "forwarded", "reasons": [], "twin_reply": {"status": "ok", "current_state": {}}})

    twin = FakeTwin()
    gateway = GuardianGateway(twin, adapter(handler))
    await gateway.call_actuator(call("set_valve_state", {"valve_id": "v", "state": "open"}))
    await gateway.call_actuator(call("broadcast_alert", {"message": "m", "channel": "siren", "zone_id": "z"}))

    assert sent == ["set_valve_state"] and twin.calls == ["broadcast_alert"] and await gateway.get_topology() == {"zones": []}


async def test_a_gateway_that_cannot_reach_the_guardian_raises_a_twin_error():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(TwinError, match="guardian gateway"):
        await adapter(down).call_actuator(call("set_valve_state", {"valve_id": "v", "state": "open"}))


def test_the_v1_adapter_is_chosen_by_config_and_refuses_to_run_without_the_key_that_checks_verdicts(monkeypatch):
    from brain.adapters import GuardianGateway, GuardianV1Adapter, RestGuardianAdapter, open_guardian, with_gateway
    from brain.config import GuardianConfig

    assert isinstance(open_guardian(GuardianConfig(), None), RestGuardianAdapter)
    v1 = GuardianConfig(adapter="v1", url="http://guardian:8003", dispatcher_id="dispatch-central")
    monkeypatch.delenv("GUARDIAN_HMAC_KEY", raising=False)
    with pytest.raises(SystemExit, match="GUARDIAN_HMAC_KEY"):
        open_guardian(v1, None)
    monkeypatch.setenv("GUARDIAN_HMAC_KEY", KEY)
    guardian = open_guardian(v1, None)

    assert isinstance(guardian, GuardianV1Adapter) and isinstance(with_gateway(FakeTwin(), guardian, v1), GuardianGateway)
    assert not isinstance(with_gateway(FakeTwin(), guardian, GuardianConfig(adapter="v1", gateway=False)), GuardianGateway)
