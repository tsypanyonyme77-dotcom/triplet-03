"""Drivers and pedestrians keep away from a burning building, and never freeze because of it."""
import math

import networkx as nx

from twin.engine.fire_hazard import (
    CAR_PENALTY_S, hazard_road_edges, hazard_walk_edges, segment_distance, walk_weight, with_car_penalties,
)
from twin.engine.routing import build_turn_graph, route_between
from twin.world.scenario import DT, build_simulation, decide_randomly


def _grid(n: int = 3) -> nx.MultiDiGraph:
    """An n x n street grid, 80 m apart, every street two-way (the two-block map has no detours to choose)."""
    g = nx.MultiDiGraph()
    for i in range(n):
        for j in range(n):
            g.add_node(i * n + j, x=i * 80.0, y=j * 80.0)
    for u, v in nx.grid_2d_graph(n, n).edges():
        a, b = u[0] * n + u[1], v[0] * n + v[1]
        for p, q in ((a, b), (b, a)):
            g.add_edge(p, q, length=80.0, travel_time=80.0 / (40 / 3.6))
    return g


def test_distance_to_a_segment():
    assert segment_distance((5, 3), (0, 0), (10, 0)) == 3
    assert segment_distance((-4, 3), (0, 0), (10, 0)) == 5      # beyond the end: to the end point
    assert segment_distance((1, 1), (2, 2), (2, 2)) == math.hypot(1, 1)


def test_only_streets_and_sidewalks_next_to_the_fire_are_hazards():
    sim = build_simulation(cars=0, pedestrians=0)
    front = sim.buildings["bld-01-03"].front                       # on the south street, x = 33
    assert hazard_road_edges(sim.graph, [front]) == {(1, 2), (2, 1)}
    walk = hazard_walk_edges(sim.walk.graph, [front])
    assert walk and len(walk) < sim.walk.graph.number_of_edges() / 4
    for edge in walk:
        a, b = tuple(edge)
        pa, pb = sim.walk.xy(a), sim.walk.xy(b)
        assert segment_distance(front, pa, pb) <= 25.0
    assert hazard_road_edges(sim.graph, []) == set()


def test_a_driver_takes_the_longer_way_round_a_hazard_and_goes_through_when_there_is_none():
    g = _grid()
    turns = build_turn_graph(g)
    start, dest = (0, 3), (1, 0)                    # in the grid, node = 3 * column + row
    plain = route_between(turns, start, 10.0, dest, 40.0, 5.0)
    assert plain == [0, 3, 4, 1, 0]
    hazard = {(4, 1)}                               # the street the plain route takes in the middle
    avoiding = route_between(with_car_penalties(turns, hazard), start, 10.0, dest, 40.0, 5.0)
    assert avoiding == [0, 3, 4, 5, 2, 1, 0]        # longer, and never enters the hazard
    # every way in is a hazard: it still gets there (a fire must not freeze the traffic)
    everything = set(g.edges())
    assert route_between(with_car_penalties(turns, everything), start, 10.0, dest, 40.0, 5.0) is not None
    weights = [d["weight"] for _, _, d in with_car_penalties(turns, hazard).edges(data=True)]
    assert max(weights) >= CAR_PENALTY_S


def test_a_walker_takes_the_longer_sidewalk_round_a_hazard():
    sim = build_simulation(cars=0, pedestrians=0)
    sim.ignite_building("bld-01-03")
    for _ in range(2):
        sim.tick(DT)
    ends = sorted(sim.walk.graph.nodes, key=lambda n: sim.walk.xy(n)[0])
    a, b = ends[0], ends[-1]
    plain = nx.shortest_path(sim.walk.graph, a, b, weight="length")
    weight = walk_weight(sim.hazard_walk_edges)
    avoiding = nx.shortest_path(sim.walk.graph, a, b, weight=weight)
    count = lambda route: sum(frozenset(e) in sim.hazard_walk_edges for e in zip(route, route[1:]))  # noqa: E731
    assert count(avoiding) <= count(plain)


def test_a_fire_makes_its_streets_costly_and_putting_it_out_makes_them_ordinary_again():
    sim = build_simulation(cars=0, pedestrians=0)
    plain = {(u, v): d["weight"] for u, v, d in sim._turns_open.edges(data=True)}
    sim.ignite_building("bld-01-03")
    sim.tick(DT)
    assert sim.hazard_edges == {(1, 2), (2, 1)}
    after = {(u, v): d["weight"] for u, v, d in sim._turns_open.edges(data=True)}
    entering = {k for k in after if k[1] in sim.hazard_edges}
    assert entering and all(after[k] == plain[k] + CAR_PENALTY_S for k in entering)
    assert all(after[k] == plain[k] for k in after if k not in entering)
    sim.fire.extinguish("fire-0001", sim._sim_time)
    sim.tick(DT)
    assert sim.hazard_edges == set() and sim.hazard_walk_edges == set()
    assert {(u, v): d["weight"] for u, v, d in sim._turns_open.edges(data=True)} == plain


def _run_city(fire: bool, seed: int = 7, seconds: float = 120.0, ignite_at: float = 20.0):
    """A busy city; with `fire`, a building on the south street burns from `ignite_at`. Returns the sim,
    pedestrian ticks spent within 25 m of that building, trips finished, and the longest time any
    pedestrian stood still, from t = 40 s on."""
    sim = build_simulation(cars=20, pedestrians=40, runners=4, seed=seed)
    front = sim.buildings["bld-01-03"].front
    near = arrivals = 0
    last: dict[str, tuple] = {}
    still: dict[str, float] = {}
    longest = 0.0
    for _ in range(round(seconds / DT)):
        if fire and sim._sim_time >= ignite_at and not sim.fire.fires:
            sim.ignite_building("bld-01-03")
        decide_randomly(sim)
        before = {p.id for p in sim.pedestrians.values() if p.status == "arrived"}
        sim.tick(DT)
        if sim._sim_time < 40.0:
            continue
        arrivals += len({p.id for p in sim.pedestrians.values() if p.status == "arrived"} - before)
        for p in sim.pedestrians.values():
            moving = p.status in ("walking", "waiting")
            near += moving and math.hypot(p.x - front[0], p.y - front[1]) <= 25.0
            pos = (round(p.x, 1), round(p.y, 1))
            still[p.id] = still.get(p.id, 0.0) + DT if moving and last.get(p.id) == pos else 0.0
            longest = max(longest, still[p.id])
            last[p.id] = pos
    return sim, near, arrivals, longest


def test_pedestrians_keep_away_from_the_fire_and_nobody_freezes():
    _, near_without, arrivals_without, longest_without = _run_city(fire=False)
    sim, near_with, arrivals_with, longest_with = _run_city(fire=True)
    assert near_with < 0.5 * near_without                          # measured 2013 -> 373 ticks (seed 7)
    assert arrivals_with > 0.3 * arrivals_without                  # detours cost trips, but they go on
    assert longest_with < 40.0 and longest_without < 40.0          # waiting at a crossing, never frozen
    assert sum(c.status == "driving" for c in sim.cars.values()) > 0


def test_nobody_heads_for_a_parking_spot_next_to_the_fire_unless_already_on_that_street():
    sim = _run_city(fire=True, seconds=100.0)[0]
    assert sim.hazard_edges                                      # the fire (and what it spread to) is still burning
    for car in sim.cars.values():
        spot = sim.parking_spots.get(car.pending_spot_id) if car.pending_spot_id else None
        if spot is None or spot.edge not in sim.hazard_edges or car.status != "driving":
            continue
        assert (car.route_nodes[car.edge_index], car.route_nodes[car.edge_index + 1]) == spot.edge, car.id
