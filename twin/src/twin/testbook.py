"""The Test Book's scenarios, as data: what triggers each one and what must be seen. TESTBOOK.md at
the repository root describes the same scenarios for people; keep the two together."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Expectation:
    layer: str   # twin | guardian | city_brain, as in the events' `layer`
    kind: str
    meaning: str


@dataclass(frozen=True)
class TestBookScenario:
    __test__ = False  # not a pytest class, despite the name

    id: str
    name: str
    engine_scenario: str
    timeout_sim_s: float
    expected: tuple[Expectation, ...]

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "engine_scenario": self.engine_scenario, "timeout_sim_s": self.timeout_sim_s,
                "expected": [e.__dict__ for e in self.expected]}


_RESPONSE = (
    Expectation("twin", "emergency_call_reading", "a witness's call leaves the Twin as a signed reading"),
    Expectation("guardian", "verdict_issued", "the Guardian judges the report"),
    Expectation("city_brain", "incident_reported", "the Brain lists the incident from a trusted report"),
    Expectation("city_brain", "actuator_called", "the Brain decides and calls an actuator"),
    Expectation("twin", "unit_dispatched", "the Twin sends a unit out of its station"),
    Expectation("twin", "sim_unit_arrived", "the unit reaches the scene"),
    Expectation("twin", "sim_casualty_loaded", "the crew loads the casualty"),
    Expectation("twin", "sim_scene_cleared", "the scene is cleared"),
    Expectation("twin", "sim_casualty_delivered", "the casualty reaches the hospital"),
)

_FIRE_RESPONSE = (
    Expectation("twin", "building_fire_reading", "the smoke sensor of the burning building leaves the Twin as a signed reading"),
    Expectation("guardian", "verdict_issued", "the Guardian judges the report"),
    Expectation("city_brain", "incident_reported", "the Brain lists the incident from a trusted report"),
    Expectation("city_brain", "actuator_called", "the Brain decides and calls an actuator"),
    Expectation("twin", "unit_dispatched", "the Twin sends a fire truck out of its station"),
    Expectation("twin", "sim_unit_arrived", "the truck reaches the building"),
    Expectation("twin", "sim_fire_extinguished", "the firefighters put the fire out"),
    Expectation("twin", "sim_scene_cleared", "the scene is cleared"),
)

SCENARIOS: dict[str, TestBookScenario] = {s.id: s for s in (
    TestBookScenario("t1", "Pedestrian hit on a crosswalk", "ped-hit", 400.0,
                     (Expectation("twin", "sim_incident", "a car hits a pedestrian"), *_RESPONSE)),
    TestBookScenario("t2", "Car crash at a junction", "car-crash", 500.0,
                     (Expectation("twin", "sim_incident", "a red-light runner hits a crossing car"), *_RESPONSE)),
    TestBookScenario("t3", "Fire in a building", "building-fire", 400.0,
                     (Expectation("twin", "sim_fire_started", "a building catches fire"), *_FIRE_RESPONSE)),
    # about 450 s with the pump started, 900 s on the storm drain alone: the timeout leaves room for both
    TestBookScenario("t4", "Flash flood from rain", "flood", 1000.0, (
        Expectation("twin", "sim_rain_started", "a cloudburst starts"),
        Expectation("twin", "sim_street_flooded", "water fills the dip of street 2-3 and careful drivers stay out"),
        Expectation("twin", "sim_incident", "a driver who ignores the water stalls in it, and a pedestrian is trapped"),
        Expectation("twin", "emergency_call_reading", "a flood call leaves the Twin as a signed reading"),
        Expectation("guardian", "verdict_issued", "the Guardian judges the report"),
        Expectation("city_brain", "incident_reported", "the Brain lists the incident from a trusted report"),
        Expectation("city_brain", "actuator_called", "the Brain decides and calls an actuator"),
        Expectation("twin", "unit_dispatched", "the Twin sends the fire truck out of its station"),
        Expectation("twin", "sim_unit_arrived", "the fire truck reaches the stalled car"),
        Expectation("twin", "sim_driver_rescued", "firefighters get the driver out"),
        Expectation("twin", "sim_pedestrian_rescued", "firefighters lead the trapped pedestrian out of the water"),
        Expectation("twin", "sim_scene_cleared", "the water is down and the car is towed away"),
    )),
)}
