"""Bids: each pack says how well it can answer an incident, given what the Twin really offers."""

from brain.config import WorkspacePolicy
from brain.contracts import Incident
from brain.departments import discover_manifests
from brain.mind.bids import bid
from brain.scenario import inproc_partners
from tests.conftest import T0
from tests.test_conditions import camera, scenario
from tests.test_scenarios import play

PACKS, _ = discover_manifests()
EVERYTHING = {"dispatch_unit", "broadcast_alert", "recall_unit", "set_signal_phase", "set_valve_state", "set_grid_connection"}


def incident(type, zone="zone-05"):
    return Incident(incident_id="inc-0001", type=type, zone_id=zone, occurred_at=T0)


def test_a_pack_bids_high_for_its_own_incident_type_and_zero_for_others(world):
    jam = incident("jam")

    assert bid(PACKS["MOBILITY"], jam, EVERYTHING, world.store).score == 1.0
    other = bid(PACKS["UTILITIES"], jam, EVERYTHING, world.store)
    assert other.score == 0.0 and "jam" in other.reason


def test_a_pack_that_needs_an_actuator_the_twin_lacks_bids_low_and_says_why(world):
    result = bid(PACKS["MOBILITY"], incident("jam"), EVERYTHING - {"set_signal_phase"}, world.store)

    assert result.score == 0.0 and "set_signal_phase" in result.reason


def test_a_dispatch_pack_bids_low_when_no_unit_is_free(world):
    fire = incident("fire", "zone-06")
    assert bid(PACKS["FIRE"], fire, EVERYTHING, world.store).score == 1.0

    for _ in range(2):
        world.store.commit_unit("fire-dispatch-04")  # the only fire station's two units are out

    low = bid(PACKS["FIRE"], fire, EVERYTHING, world.store)
    assert low.score == 0.3 and "fire" in low.reason


def test_a_pack_without_explicit_bids_bids_for_each_of_its_incident_types(world):
    assert bid(PACKS["POLICE"], incident("crime", "zone-07"), EVERYTHING, world.store).score == 1.0


async def test_ignition_reports_the_bids_and_who_is_recruited():
    result = await play(scenario([camera(100, 0.85)]))

    (event,) = result.sink.of("brain.pack.bid")
    assert event.subject == "inc-0001" and event.data["recruited"] == ["MOBILITY"]
    assert {b["pack"] for b in event.data["bids"]} == {"POLICE", "FIRE", "MEDICAL", "MOBILITY", "DISASTER", "UTILITIES"}
    assert result.sink.of("brain.pack.uncovered") == []
    assert result.sink.types().index("brain.workspace.ignited") < result.sink.types().index("brain.pack.bid")


async def test_a_twin_without_signal_control_leaves_the_jam_uncovered():
    result = await play(scenario([camera(100, 0.85)]), inproc_partners(frozenset({"set_signal_phase"})))

    (event,) = result.sink.of("brain.pack.uncovered")
    assert "set_signal_phase" in event.data["reasons"]["MOBILITY"]
    assert result.actuator_calls == []
    assert [e.data["check"] for e in result.sink.of("brain.action.blocked")] == ["capability"]  # the reflex still tries, the gate says no


def test_the_default_recruiting_line_is_half():
    assert WorkspacePolicy().recruit_at == 0.5
