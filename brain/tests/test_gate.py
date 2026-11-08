from datetime import timedelta

import pytest

from brain.config import GatePolicy
from brain.contracts import ActuatorCall, ActuatorResult, ProposedAction, utcnow
from brain.contracts.signing import verify
from brain.departments import load_manifest
from brain.gate import ActuationGate, idempotency_key
from brain.ports import GuardianUnavailable


class RecordingTwin:
    def __init__(self) -> None:
        self.calls: list[ActuatorCall] = []

    async def call_actuator(self, call: ActuatorCall) -> ActuatorResult:
        self.calls.append(call)
        return ActuatorResult(status="dispatched", unit_id="unit-p-01")


class StubGuardian:
    def __init__(self, quarantined=(), down=False) -> None:
        self.quarantined, self.down = set(quarantined), down

    async def is_quarantined(self, device_id: str) -> bool:
        if self.down:
            raise GuardianUnavailable("no answer")
        return device_id in self.quarantined


def make_gate(world, twin=None, guardian=None, policy=None, capabilities=("dispatch_unit", "broadcast_alert"), secret="test-brain-secret"):
    return ActuationGate(world.store, twin or RecordingTwin(), guardian or StubGuardian(), policy or GatePolicy(),
                         {"POLICE": load_manifest("police")}, set(capabilities), signing_secret=secret)


@pytest.fixture
def setup(world):
    incident = world.crime(at_s=10)
    presence = world.sighting("cit-2", "zone-07", at_s=9)
    flight = world.sighting("cit-2", "zone-08", at_s=20, speed=18, activity="running")
    twin = RecordingTwin()
    crime = incident.evidence[0]
    proposal = ProposedAction(
        department="POLICE", tier="reflex", incident_id=incident.incident_id, action="dispatch_unit",
        actuator_id="police-dispatch-05",
        params={"unit_type": "police", "zone_id": "zone-08", "incident_id": incident.incident_id,
                "mode": "pursuit", "target_id": "cit-2"},
        justification="test", trust_ref=world.store.verdict_of(crime).verdict_id,
        evidence_reading_ids=[crime, presence, flight],
    )
    return world, make_gate(world, twin), twin, proposal


async def test_a_well_founded_proposal_is_signed_and_sent(setup):
    _, gate, twin, proposal = setup

    decision = await gate.check(proposal)
    assert decision.allowed, decision.reason
    envelope, result = await gate.execute(decision.approval_id)

    assert result.status == "dispatched"
    assert twin.calls[0].trust_ref == proposal.trust_ref
    assert twin.calls[0].requesting_layer == "city_brain"
    assert verify(envelope, "test-brain-secret")


async def test_an_approval_can_be_used_only_once_and_cannot_be_forged(setup):
    _, gate, twin, proposal = setup
    decision = await gate.check(proposal)
    await gate.execute(decision.approval_id)

    with pytest.raises(PermissionError):
        await gate.execute(decision.approval_id)
    with pytest.raises(PermissionError):
        await gate.execute("made-up-approval")
    assert len(twin.calls) == 1


async def test_the_same_action_for_the_same_target_is_not_issued_twice(setup):
    _, gate, _, proposal = setup
    first = await gate.check(proposal)

    while_pending = await gate.check(proposal)
    await gate.execute(first.approval_id)
    after_sending = await gate.check(proposal)

    assert (while_pending.check, after_sending.check) == ("idempotency", "idempotency")


def test_one_pursuit_per_target_one_perimeter_unit_per_zone(setup):
    _, _, _, proposal = setup

    def with_params(**changes):
        return proposal.model_copy(update={"params": {**proposal.params, **changes}})

    assert idempotency_key(proposal) == idempotency_key(with_params(zone_id="zone-09"))  # pursuit follows the target
    contain_04, contain_08 = with_params(mode="contain", zone_id="zone-04"), with_params(mode="contain", zone_id="zone-08")
    assert len({idempotency_key(p) for p in (proposal, contain_04, contain_08)}) == 3


@pytest.mark.parametrize(
    ("change", "failed_check"),
    [
        ({"trust_ref": None}, "trust_ref"),
        ({"trust_ref": "verdict-does-not-exist"}, "trust_ref"),
        ({"action": "set_grid_connection", "params": {"zone_id": "zone-07", "state": "disconnected"}}, "capability"),
        ({"params": {"unit_type": "fire", "zone_id": "zone-08", "incident_id": "inc-0001"}}, "allowlist"),
        ({"params": {"unit_type": "police", "zone_id": "zone-08"}}, "schema"),
        ({"params": {"unit_type": "police", "zone_id": "zone-08", "incident_id": "inc-0001", "surprise": 1}}, "schema"),
        ({"action": "broadcast_alert", "params": {"message": "", "channel": "app", "zone_id": "zone-07"}}, "schema"),
        ({"department": "FIRE"}, "allowlist"),
    ],
)
async def test_denied(setup, change, failed_check):
    _, gate, _, proposal = setup

    decision = await gate.check(proposal.model_copy(update=change))

    assert not decision.allowed
    assert decision.check == failed_check
    assert decision.reason


async def test_a_single_trusted_source_is_not_enough_to_dispatch(setup):
    _, gate, _, proposal = setup

    decision = await gate.check(proposal.model_copy(update={"evidence_reading_ids": proposal.evidence_reading_ids[:1]}))

    assert not decision.allowed and decision.check == "evidence"


async def test_a_low_impact_alert_needs_only_one_trusted_source(setup):
    _, gate, _, proposal = setup
    alert = proposal.model_copy(update={
        "action": "broadcast_alert", "actuator_id": "broadcast-alert-zone-07",
        "params": {"message": "Police activity in Downtown.", "channel": "app", "zone_id": "zone-07"},
        "evidence_reading_ids": proposal.evidence_reading_ids[:1],
    })

    assert (await gate.check(alert)).allowed


async def test_untrusted_verdict_blocks(world):
    incident = world.crime(at_s=10, status="untrusted")
    crime = incident.evidence[0]
    proposal = ProposedAction(
        department="POLICE", tier="reflex", incident_id="inc-0001", action="dispatch_unit", actuator_id="x",
        params={"unit_type": "police", "zone_id": "zone-07", "incident_id": "inc-0001"},
        justification="test", trust_ref=world.store.verdict_of(crime).verdict_id, evidence_reading_ids=[crime],
    )

    decision = await make_gate(world, secret=None).check(proposal)

    assert not decision.allowed and decision.check == "trust_ref"
    assert "untrusted" in decision.reason


async def test_expired_verdict_blocks(setup):
    _, gate, _, proposal = setup

    decision = await gate.check(proposal, now=utcnow() + timedelta(hours=1))

    assert not decision.allowed and decision.check == "trust_ref"
    assert "expired" in decision.reason


async def test_verdict_must_cover_cited_evidence(setup):
    _, gate, _, proposal = setup

    decision = await gate.check(proposal.model_copy(update={"evidence_reading_ids": proposal.evidence_reading_ids[1:]}))

    assert not decision.allowed and decision.check == "trust_ref"


async def test_a_quarantined_actuator_is_refused_and_remembered(setup):
    world, _, _, proposal = setup
    gate = make_gate(world, guardian=StubGuardian(quarantined=["police-dispatch-05"]))

    decision = await gate.check(proposal)

    assert not decision.allowed and decision.check == "quarantine"
    assert world.store.nearest_facility("zone-08", "police_station")["id"] == "ps-09"  # ps-05 is no longer offered


async def test_when_the_guardian_cannot_say_only_low_impact_actions_pass(setup):
    world, _, _, proposal = setup
    gate = make_gate(world, guardian=StubGuardian(down=True))
    alert = proposal.model_copy(update={
        "action": "broadcast_alert", "actuator_id": "broadcast-alert-zone-07",
        "params": {"message": "Police activity in Downtown.", "channel": "app", "zone_id": "zone-07"},
    })

    assert (await gate.check(proposal)).check == "quarantine"
    assert (await gate.check(alert)).allowed


async def test_the_actuation_budget_stops_a_runaway_planner(setup):
    world, _, _, proposal = setup
    gate = make_gate(world, policy=GatePolicy(max_actions_per_incident=2))

    def contain(zone):
        return proposal.model_copy(update={"params": {**proposal.params, "mode": "contain", "zone_id": zone}})

    checks = [(await gate.check(contain(zone))).check for zone in ("zone-04", "zone-05", "zone-08")]

    assert checks == ["passed", "passed", "budget"]


def _with_a_second_camera(setup, **policy):
    world, _, twin, proposal = setup
    second = world.reading("cam-07-03", "cctv_anomaly", "zone-07", {"anomaly_type": "robbery", "confidence": 0.8}, 11)
    crime = proposal.evidence_reading_ids[0]
    return make_gate(world, twin, policy=GatePolicy(**policy)), proposal.model_copy(update={"evidence_reading_ids": [crime, second]})


async def test_by_default_two_cameras_in_one_zone_are_two_sources(setup):
    gate, proposal = _with_a_second_camera(setup)

    assert (await gate.check(proposal)).allowed


async def test_counting_causes_two_cameras_in_one_zone_are_one_witness(setup):
    gate, proposal = _with_a_second_camera(setup, independence="cause")

    decision = await gate.check(proposal)

    assert not decision.allowed and decision.check == "evidence" and "found 1" in decision.reason


async def test_counting_causes_a_camera_and_a_call_are_two_witnesses(setup):
    world, _, twin, proposal = setup
    call = world.reading("call-feed-07", "emergency_call", "zone-07", {"call_id": "c7", "category": "police"}, 11)
    gate = make_gate(world, twin, policy=GatePolicy(independence="cause"))

    decision = await gate.check(proposal.model_copy(update={"evidence_reading_ids": [proposal.evidence_reading_ids[0], call]}))

    assert decision.allowed


# --- a cooling-off for an actuator that flaps ---------------------------------------------------------------------------


def signal_proposal(world, at_s, actuator="signal-05-01", sensor="tcam-05-01"):
    reading = world.reading(sensor, "traffic_camera", "zone-05", {"congestion_score": 0.9, "vehicle_count": 40, "avg_speed_kmh": 4.0}, at_s)
    return ProposedAction(
        department="MOBILITY", tier="reflex", incident_id="inc-0001", action="set_signal_phase", actuator_id=actuator,
        params={"intersection_id": actuator.replace("signal", "sig"), "phase": "green", "duration_s": 120},
        justification="test", trust_ref=world.store.verdict_of(reading).verdict_id, evidence_reading_ids=[reading],
    )


def mobility_gate(world, **policy):
    return ActuationGate(world.store, RecordingTwin(), StubGuardian(), GatePolicy(**policy), {"MOBILITY": load_manifest("mobility")},
                         {"set_signal_phase", "dispatch_unit"}, signing_secret="test-brain-secret")


async def test_by_default_the_same_signal_may_be_driven_twice_in_a_row(world):
    gate = mobility_gate(world)
    first, second = signal_proposal(world, 10), signal_proposal(world, 20)

    assert (await gate.check(first)).allowed
    second = second.model_copy(update={"incident_id": "inc-0002"})  # a second jam is a new incident, so a new key
    assert (await gate.check(second)).allowed


async def test_inside_the_gap_the_same_actuator_is_refused_and_the_reason_says_when_it_may_be_driven_again(world):
    gate = mobility_gate(world, min_gap_s={"set_signal_phase": 60})
    assert (await gate.check(signal_proposal(world, 10))).allowed

    refused = await gate.check(signal_proposal(world, 40).model_copy(update={"incident_id": "inc-0002"}))

    assert not refused.allowed and refused.check == "cooling"
    assert "30 s ago" in refused.reason and "60 s" in refused.reason


async def test_after_the_gap_the_actuator_may_be_driven_again(world):
    gate = mobility_gate(world, min_gap_s={"set_signal_phase": 60})
    assert (await gate.check(signal_proposal(world, 10))).allowed

    assert (await gate.check(signal_proposal(world, 80).model_copy(update={"incident_id": "inc-0002"}))).allowed


async def test_another_actuator_is_not_held_by_the_first_ones_gap(world):
    gate = mobility_gate(world, min_gap_s={"set_signal_phase": 60})
    assert (await gate.check(signal_proposal(world, 10))).allowed

    other = signal_proposal(world, 20, actuator="signal-05-02")

    assert (await gate.check(other)).allowed


async def test_the_gap_is_remembered_across_a_restart(world):
    gate = mobility_gate(world, min_gap_s={"set_signal_phase": 60})
    assert (await gate.check(signal_proposal(world, 10))).allowed
    saved = gate.snapshot()

    again = mobility_gate(world, min_gap_s={"set_signal_phase": 60})
    again.restore(saved)

    refused = await again.check(signal_proposal(world, 30).model_copy(update={"incident_id": "inc-0002"}))
    assert not refused.allowed and refused.check == "cooling"


async def test_a_stand_down_is_never_held_by_a_gap(setup):
    world, _, twin, proposal = setup
    gate = make_gate(world, twin, policy=GatePolicy(min_gap_s={"recall_unit": 3600}))
    unit = world.store.commit_unit("police-dispatch-05", "unit-p-01", incident_id=proposal.incident_id, mode="contain", zone_id="zone-08", target_id="x", key="k")
    recall = proposal.model_copy(update={"action": "recall_unit", "params": {"unit_id": "unit-p-01", "incident_id": proposal.incident_id}})

    first = await gate.check(recall)

    assert first.allowed or first.check != "cooling"


async def test_the_gate_reports_the_facts_behind_each_check_it_passed(setup):
    _, gate, _, proposal = setup

    decision = await gate.check(proposal)

    assert decision.allowed
    assert decision.detail["checks"] == ["schema", "capability", "allowlist", "incident", "trust_ref", "evidence", "idempotency", "quarantine", "budget"]
    assert decision.detail["impact"] == "medium" and decision.detail["needed_sources"] == 2
    assert len(decision.detail["witnesses"]) >= 2


async def test_a_refusal_carries_the_numbers_that_decided_it(setup):
    world, gate, _, proposal = setup
    lone = proposal.model_copy(update={"evidence_reading_ids": proposal.evidence_reading_ids[:1]})

    thin = await gate.check(lone)
    assert not thin.allowed and thin.check == "evidence"
    assert thin.detail["needed_sources"] == 2 and len(thin.detail["witnesses"]) == 1
    assert thin.detail["checks"] == ["schema", "capability", "allowlist", "incident", "trust_ref"]  # what passed before it

    unknown = await gate.check(proposal.model_copy(update={"trust_ref": "verdict-missing"}))
    assert unknown.check == "trust_ref" and unknown.detail == {"checks": ["schema", "capability", "allowlist", "incident"], "verdict_id": "verdict-missing", "verdict_status": "unknown"}


class DownThenUpTwin(RecordingTwin):
    def __init__(self) -> None:
        super().__init__()
        self.down = True

    async def call_actuator(self, call: ActuatorCall) -> ActuatorResult:
        if self.down:
            raise ConnectionError("twin unreachable")
        return await super().call_actuator(call)


def _gate_over_a_down_twin(setup, **policy):
    world, _, _, proposal = setup
    twin = DownThenUpTwin()
    return make_gate(world, twin, policy=GatePolicy(**policy)), twin, proposal


async def test_a_dispatch_the_twin_never_answered_may_be_tried_again(setup):
    gate, twin, proposal = _gate_over_a_down_twin(setup)
    first = await gate.check(proposal)
    with pytest.raises(ConnectionError):
        await gate.execute(first.approval_id)
    twin.down = False
    again = await gate.check(proposal)
    assert again.allowed, again.reason
    _, result = await gate.execute(again.approval_id)
    assert result.status == "dispatched"


async def test_with_retry_off_a_dispatch_the_twin_never_answered_stays_spent(setup):
    gate, _, proposal = _gate_over_a_down_twin(setup, retry_unreached=False)
    first = await gate.check(proposal)
    with pytest.raises(ConnectionError):
        await gate.execute(first.approval_id)
    again = await gate.check(proposal)
    assert not again.allowed and again.check == "idempotency"
