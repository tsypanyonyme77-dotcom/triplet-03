"""Buildings: a ring of boxes around each block of the two-block map, known to the engine."""
import math

from twin.engine.buildings import adjacency
from twin.engine.street_profile import SIDEWALK_WIDTH_M, kerb_offset
from twin.world import scenarios
from twin.world.buildings import build_buildings
from twin.world.map import build_two_blocks_graph
from twin.world.record import map_section


def _two_blocks():
    graph = build_two_blocks_graph()
    return graph, build_buildings(graph)


def test_each_block_is_ringed_with_twelve_buildings_with_unique_ids():
    _, buildings = _two_blocks()
    assert len(buildings) == 24
    assert len({b.id for b in buildings}) == 24
    assert sum(b.id.startswith("bld-01-") for b in buildings) == 12


def test_buildings_stand_behind_the_sidewalks_and_never_overlap():
    graph, buildings = _two_blocks()
    line = kerb_offset(graph, 1, 2) + SIDEWALK_WIDTH_M
    for b in buildings:
        near_street = min(
            min(abs(b.x - sx) for sx in (0.0, 80.0, 160.0)) - b.width / 2,
            min(abs(b.y - sy) for sy in (0.0, 80.0)) - b.depth / 2,
        )
        assert near_street >= line - 1e-6, f"{b.id} reaches into the street"
    for i, a in enumerate(buildings):
        for b in buildings[i + 1:]:
            assert a.gap_to(b) > 0.0, f"{a.id} overlaps {b.id}"


def test_every_building_can_be_seen_from_its_street():
    sim = scenarios.build("city").sim
    assert len(sim.buildings) == 24
    for b in sim.buildings.values():
        assert sim.corridors.open_at(*b.front), f"{b.id}: front point is not in the street corridor"
        assert b.street in {(1, 2), (2, 3), (4, 5), (5, 6), (1, 4), (2, 5), (3, 6)}


def test_a_fire_can_only_spread_between_buildings_that_touch():
    _, buildings = _two_blocks()
    next_to = adjacency(buildings)
    by_id = {b.id: b for b in buildings}
    for bid, others in next_to.items():
        assert others, f"{bid} has no neighbour"
        for other in others:
            assert bid in next_to[other]                       # symmetric
            assert by_id[bid].gap_to(by_id[other]) <= 3.0
            assert math.hypot(by_id[bid].x - by_id[other].x, by_id[bid].y - by_id[other].y) < 30.0
    # across a street (24 m of street and sidewalks) is too far: no building touches another block's
    for bid, others in next_to.items():
        assert {o[:6] for o in others} == {bid[:6]}


def test_the_map_section_lists_the_buildings_for_the_viewer():
    sim = scenarios.build("city").sim
    listed = map_section(sim)["buildings"]
    assert [b["id"] for b in listed] == [b.id for b in sim.buildings.values()]
    assert {"id", "x", "y", "width", "depth", "height", "front", "street"} <= set(listed[0])
