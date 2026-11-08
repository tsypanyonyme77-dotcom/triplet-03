"""Pedestrian network on the two-block map: shape, connectivity, placement."""
import networkx as nx

from twin.engine.street_profile import CROSSWALK_WIDTH_M, STOP_LINE_GAP_M
from twin.engine.traffic_lights import build_traffic_lights
from twin.engine.walk_network import build_walk_network
from tools.check_rules import on_asphalt_outside_crosswalk
from twin.world.map import build_two_blocks_graph


def _network():
    road = build_two_blocks_graph()
    return build_walk_network(road, set(build_traffic_lights(road)))


def test_crosswalks_on_every_arm_of_each_t_junction():
    walk = _network()
    assert sorted(walk.crosswalks) == ["cw_2_1", "cw_2_3", "cw_2_5", "cw_5_2", "cw_5_4", "cw_5_6"]
    assert all(cw.signalised for cw in walk.crosswalks.values())


def test_walk_network_is_connected():
    assert nx.is_connected(_network().graph)


def test_walk_nodes_are_never_on_the_road():
    walk = _network()
    for node in walk.graph.nodes:
        assert not on_asphalt_outside_crosswalk(*walk.xy(node)), walk.xy(node)


def test_only_crosswalk_edges_cross_a_street():
    walk = _network()
    for a, b, data in walk.graph.edges(data=True):
        (ax, ay), (bx, by) = walk.xy(a), walk.xy(b)
        mid = ((ax + bx) / 2, (ay + by) / 2)
        if data["kind"] != "crosswalk":
            assert not on_asphalt_outside_crosswalk(*mid), (data["kind"], mid)


def test_stop_line_sits_before_the_crosswalk():
    walk = _network()
    cw = walk.crosswalk_at(2, 1)
    assert walk.stop_setback(1, 2) == cw.along_m + CROSSWALK_WIDTH_M / 2 + STOP_LINE_GAP_M
    assert walk.stop_setback(1, 4) is None  # node 4 is a simple bend: no crosswalk, no stop line
