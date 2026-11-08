"""A counterfactual is a claim: "had this been different, the action would have gone through". Each one the explanation can make is
applied here to the real check it names, and the outcome must flip (or, for human approval, must not)."""

import re
from pathlib import Path

from brain.config import GatePolicy, ScoringPolicy
from brain.contracts import ProposedAction
from brain.departments.police import assess
from brain.explain import REGION, held_counterfactuals
from brain.mind.forward import ForwardModels
from tests.test_forward import Feed
from tests.test_gate import StubGuardian, make_gate

ROOT = Path(__file__).resolve().parent.parent


def proposal_for(world, status="trusted", zone="zone-08", mode="pursuit", extra_flight_at=None, **changes) -> ProposedAction:
    incident = world.crime(at_s=10, status=status)
    presence = world.sighting("cit-2", "zone-07", at_s=9)
    flight = world.sighting("cit-2", "zone-08", at_s=20, speed=18, activity="running")
    evidence = [incident.evidence[0], presence, flight]
    if extra_flight_at is not None:
        evidence.append(world.sighting("cit-2", "zone-09", at_s=extra_flight_at, speed=18, activity="running"))
    params = {"unit_type": "police", "zone_id": zone, "incident_id": incident.incident_id, "mode": mode, "target_id": "cit-2"}
    return ProposedAction(
        department="POLICE", tier="reflex", incident_id=incident.incident_id, action="dispatch_unit", actuator_id="police-dispatch-05",
        params=params, justification="test", trust_ref=world.store.verdict_of(incident.evidence[0]).verdict_id,
        evidence_reading_ids=evidence, **changes,
    )


async def refused(gate, proposal, check):
    decision = await gate.check(proposal)
    assert not decision.allowed and decision.check == check, (decision.check, decision.reason)
    data = {"check": decision.check, "reason": decision.reason, "gate": decision.detail}
    return held_counterfactuals(data)


async def test_a_second_independent_source_releases_an_action_held_for_evidence(world):
    full = proposal_for(world)
    gate = make_gate(world)
    lone = full.model_copy(update={"evidence_reading_ids": full.evidence_reading_ids[:1]})

    (flip,) = await refused(gate, lone, "evidence")

    assert flip.would_flip and flip.change.startswith("A second independent trusted source (1 found, 2 needed)")
    assert (await gate.check(full)).allowed


async def test_a_trusted_verdict_releases_an_action_held_for_trust_ref(world):
    untrusted = proposal_for(world, status="untrusted")

    (flip,) = await refused(make_gate(world), untrusted, "trust_ref")
    assert flip.would_flip and "untrusted" in flip.change

    from tests.conftest import World
    other = World()
    assert (await make_gate(other).check(proposal_for(other))).allowed


async def test_fewer_earlier_actions_release_an_action_held_for_the_budget(world):
    policy = GatePolicy(max_actions_per_incident=1)
    first = proposal_for(world)
    second = first.model_copy(update={"params": {**first.params, "zone_id": "zone-09", "mode": "contain"}})
    gate = make_gate(world, policy=policy)
    assert (await gate.check(first)).allowed

    (flip,) = await refused(gate, second, "budget")

    assert flip.would_flip and "Fewer than 1 earlier actions in this incident" in flip.change
    assert (await make_gate(world, policy=policy).check(second)).allowed


async def test_releasing_the_quarantine_releases_an_action_held_for_it(world):
    proposal = proposal_for(world)

    (flip,) = await refused(make_gate(world, guardian=StubGuardian(quarantined={"police-dispatch-05"})), proposal, "quarantine")

    assert flip.would_flip
    assert (await make_gate(world, guardian=StubGuardian()).check(proposal)).allowed


async def test_an_actuator_the_twin_exposes_releases_an_action_held_for_capability(world):
    proposal = proposal_for(world)

    (flip,) = await refused(make_gate(world, capabilities=("broadcast_alert",)), proposal, "capability")

    assert flip.would_flip
    assert (await make_gate(world, capabilities=("dispatch_unit",)).check(proposal)).allowed


async def test_more_evidence_does_not_release_an_action_held_for_human_approval(world):
    policy = GatePolicy(impact={"dispatch_unit": "high"})
    proposal = proposal_for(world)
    gate = make_gate(world, policy=policy)

    (flip,) = await refused(gate, proposal, "human_approval")
    assert not flip.would_flip and "approval" in flip.change

    richer = proposal_for(world, extra_flight_at=30)
    assert (await gate.check(richer)).check == "human_approval"  # a fourth source changes nothing


async def test_waiting_out_the_gap_releases_an_action_held_for_cooling(world):
    policy = GatePolicy(min_gap_s={"dispatch_unit": 60})
    first = proposal_for(world)
    gate = make_gate(world, policy=policy)
    assert (await gate.check(first)).allowed
    second = first.model_copy(update={"params": {**first.params, "zone_id": "zone-09", "mode": "respond"}})

    (flip,) = await refused(gate, second, "cooling")

    assert flip.would_flip and "60 s since the actuator was last driven" in flip.change
    later = proposal_for(world, extra_flight_at=100).model_copy(update={"params": second.params})
    assert (await gate.check(later)).allowed  # the newest reading is now 80 s after the first drive


def test_a_station_with_a_unit_releases_an_action_held_for_resources(world):
    for station, actuator in (("ps-05", "police-dispatch-05"), ("ps-09", "police-dispatch-09")):
        for n in range(2):
            world.store.commit_unit(actuator, f"unit-{station}-{n}", incident_id="inc-0001", mode="respond")
    assert world.store.nearest_facility("zone-07", "police_station", need_unit=True) is None

    assert held_counterfactuals({"check": "resources", "reason": "no station has a unit available"})[0].would_flip
    world.store.release_unit("unit-ps-05-0")
    assert world.store.nearest_facility("zone-07", "police_station", need_unit=True) is not None


def test_a_trusted_reading_releases_a_pursuit_held_for_trust(world):
    incident = world.crime(at_s=10, status="untrusted")
    world.sighting("cit-2", "zone-07", at_s=9)
    world.sighting("cit-2", "zone-08", at_s=20, speed=18, activity="running")
    held = assess(incident, "cit-2", world.store, ScoringPolicy())
    assert held.level == "none" and held.raw_score >= ScoringPolicy().suspect_threshold

    (flip,) = held_counterfactuals({"check": "trust", "reason": "untrusted", "discounted_evidence": held.discounted})

    assert flip.would_flip and "cam-07-02#1" in flip.change and "untrusted" in flip.change
    from tests.conftest import World
    other = World()
    trusted = other.crime(at_s=10)
    other.sighting("cit-2", "zone-07", at_s=9)
    other.sighting("cit-2", "zone-08", at_s=20, speed=18, activity="running")
    assert assess(trusted, "cit-2", other.store, ScoringPolicy()).level == "suspect"


def test_a_second_agreeing_reading_releases_an_action_held_for_a_surprise():
    feed = Feed(ForwardModels(__import__("brain.config", fromlist=["ForwardPolicy"]).ForwardPolicy()))
    feed.calm(10)
    first, _ = feed.send(1.1)
    assert feed.models.is_doubted(first.reading_id)

    (flip,) = held_counterfactuals({"check": "surprise", "reason": "1 reading jumped far outside the sensor's own history"})

    assert flip.would_flip and "agreeing" in flip.change
    feed.send(1.3)
    assert not feed.models.is_doubted(first.reading_id)


def test_the_regions_of_an_explanation_are_the_ones_the_canopy_draws_for_the_same_events():
    page = (ROOT / "src/brain/api/static/index.html").read_text()
    pulses = dict(re.findall(r'case "(brain\.[a-z.]+)": return \[([^\]]*)\]', page[page.index("function pulsesFor"):]))
    assert pulses  # the page still has its path table
    for event_type, edges in pulses.items():
        if event_type in REGION:
            ends = {end for edge in re.findall(r'"([a-z]+)>([a-z]+)"', edges) for end in edge}
            assert REGION[event_type] in ends, (event_type, REGION[event_type], ends)
