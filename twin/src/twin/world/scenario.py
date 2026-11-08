"""Builds a Simulation on the two-block map with random destinations instead of
the LLM. Shared by the recorder, the rule checks and the tests.
"""
from __future__ import annotations

import random

import twin.engine.sim as sim_module
from twin.world.buildings import build_buildings
from twin.world.map import STATIONS, build_two_blocks_graph, flood_zones

DT = 0.1
RUN_SPEED_MS = 3.0
DWELL_S = (3.0, 10.0)  # engine default is 10-60 s; shorter keeps the small scene busy


def build_simulation(
    cars: int = 5,
    pedestrians: int = 5,
    runners: int = 2,
    distracted: int = 0,
    seed: int = 7,
    car_crash_risk: float = 0.0,
    ped_hit_risk: float = 0.0,
    fire_risk: float = 0.0,
    building_places: bool = False,
    flood_risk: float = 0.0,
) -> sim_module.Simulation:
    """`runners` pedestrians want 3 m/s instead of 1.4; the next `distracted` ones
    ignore signals and traffic gaps at crosswalks (they still only cross there).
    Car-car random crashes are off; car-pedestrian accidents are still detected.
    Two random risks make accidents happen on their own, each drawn per road user:
    `car_crash_risk` is the chance that a car runs red lights and does not wait for a free
    junction; `ped_hit_risk` is the chance that a car does not yield to pedestrians, and that a
    pedestrian ignores signals and traffic gaps at crosswalks. 0 (the default) keeps traffic
    accident-free. `fire_risk` is the chance that a building is fire-prone and catches fire once,
    at a random moment in the first few minutes (engine/fires.py); `flood_risk` the chance that a street's
    drain blocks and a downpour floods it, once (engine/flood_response.py). Neither changes the traffic.
    Red-light runners also drive into flooded streets, and pedestrians who ignore signals walk into deep water."""
    random.seed(seed)
    # dwell times are module constants in the engine, read at call time
    sim_module.DWELL_MIN_S, sim_module.DWELL_MAX_S = DWELL_S
    graph = build_two_blocks_graph()
    sim = sim_module.Simulation(graph=graph, stations=STATIONS, incident_seed=seed, buildings=build_buildings(graph),
                                 building_places=building_places)
    sim.crash_risk_multiplier = 0.0
    sim.flood_zones = flood_zones(sim.graph)  # dry until a scenario makes it rain
    for i in range(cars):
        car = sim.spawn_agent_car(car_id=f"car{i}")
        if car_crash_risk and random.random() < car_crash_risk:
            car.obeys_signals = car.respects_junctions = False
            car.ignores_flood = True
        if ped_hit_risk and random.random() < ped_hit_risk:
            car.yield_to_pedestrians = False
    for i in range(pedestrians):
        ped = sim.spawn_agent_pedestrian(ped_id=f"ped{i}")
        if i < runners:
            ped.force.desired_speed = RUN_SPEED_MS
        if runners <= i < runners + distracted:
            ped.distracted = True
        elif ped_hit_risk and random.random() < ped_hit_risk:
            ped.distracted = True
        ped.ignores_flood = ped.distracted
    sim.fire.arm(fire_risk)
    sim.arm_floods(flood_risk)
    return sim


def decide_randomly(sim: sim_module.Simulation) -> None:
    """What main.py's LLM loop does, with a random place for every decision
    (apply_decision falls back to a random place when given no place id)."""
    for car in sim.cars_needing_decision():
        sim.apply_decision(car.id, None)
    for ped in sim.pedestrians_needing_decision():
        sim.apply_pedestrian_decision(ped.id, None)


def step(sim: sim_module.Simulation, decider=None) -> None:
    """One tick. `decider` (twin.engine.decision.Decider) chooses the places; without one they are random."""
    if decider is None:
        decide_randomly(sim)
    else:
        decider.decide(sim)
    sim.tick(DT)
