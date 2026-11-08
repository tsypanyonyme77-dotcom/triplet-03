"""The reflex-only departments for fire and ambulance, traffic and utilities."""

import pytest

from brain.contracts import Incident
from brain.departments import load_manifest, load_rules
from brain.graph.actuation import Actuation, make_proposal
from tests.conftest import T0


@pytest.mark.parametrize(("name", "code"), [("fire", "FIRE"), ("medical", "MEDICAL"), ("mobility", "MOBILITY"), ("disaster", "DISASTER"), ("utilities", "UTILITIES")])
def test_each_new_department_loads_with_its_rules_stamped_with_its_code(name, code):
    manifest = load_manifest(name)

    rules = load_rules(manifest.reflex_rules, code)

    assert manifest.code == code
    assert rules
    assert all(rule.department == code and rule.scope == "condition" for rule in rules)


def test_a_department_may_use_only_the_actuators_it_lists():
    assert load_manifest("mobility").allows("set_valve_state", {}) is False
    assert load_manifest("fire").allows("dispatch_unit", {"unit_type": "fire"}) is True
    assert load_manifest("fire").allows("dispatch_unit", {"unit_type": "ambulance"}) is False
    assert load_manifest("medical").allows("dispatch_unit", {"unit_type": "ambulance"}) is True
    assert load_manifest("disaster").allows("set_valve_state", {"valve_id": "v"}) is True
    assert load_manifest("utilities").allows("set_valve_state", {"valve_id": "v"}) is False


def condition_incident(type: str, zone_id: str) -> Incident:
    return Incident(incident_id="inc-0002", type=type, zone_id=zone_id, occurred_at=T0)


def act_for(world, code: str) -> Actuation:
    return Actuation(world.store, None, None, load_manifest(code), "hash", manifests={
        m.code: m for m in map(load_manifest, ("police", "fire", "medical", "mobility", "disaster", "utilities"))})


def test_a_fire_dispatch_picks_the_nearest_fire_station_not_a_police_station(world):
    act = act_for(world, "fire")
    incident = condition_incident("fire", "zone-06")

    proposal = make_proposal(act, incident, [], "dispatch_unit",
                             {"unit_type": "fire", "zone_id": "zone-06", "incident_id": "inc-0002", "mode": "respond"},
                             tier="reflex", justification="test", manifest=act.manifests["FIRE"])

    assert proposal.actuator_id == "fire-dispatch-04"
    assert proposal.department == "FIRE"


def test_an_ambulance_dispatch_comes_from_the_hospital(world):
    act = act_for(world, "medical")

    proposal = make_proposal(act, condition_incident("accident", "zone-05"), [], "dispatch_unit",
                             {"unit_type": "ambulance", "zone_id": "zone-05", "incident_id": "inc-0002", "mode": "respond"},
                             tier="reflex", justification="test", manifest=act.manifests["MEDICAL"])

    assert proposal.actuator_id == "ambulance-dispatch-03"


def test_the_police_station_choice_is_unchanged(world):
    act = act_for(world, "police")
    incident = world.crime()
    expected = world.store.nearest_facility("zone-07", "police_station", need_unit=True)["actuator_id"]

    proposal = make_proposal(act, incident, [], "dispatch_unit",
                             {"unit_type": "police", "zone_id": "zone-07", "incident_id": incident.incident_id, "mode": "pursuit"},
                             tier="reflex", justification="test")

    assert proposal.actuator_id == expected
    assert proposal.department == "POLICE"
