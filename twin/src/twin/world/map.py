"""A hand-built road graph: two city blocks side by side with streets around them.

    n4 ------ n5 ------ n6
    |         |         |
    |  block  |  block  |
    |    A    |    B    |
    n1 ------ n2 ------ n3

Same shape and edge attributes as the OSMnx graph the POC loads
(road_network.load_road_graph), so Simulation runs on it unchanged:
nodes carry projected x/y in metres, edges carry length, lanes (per direction),
oneway, highway, speed_kph and travel_time. Every street is two-way.

Street 2-3 has a dip, the low point of the map: rain on the 8 ha that drain into it (the two blocks
and the slope above them) collects there (FLOOD_DIP, flood_zones; the water model is engine/flood.py).
Its low point is 38 m east of node 2 (x = 118), and it is 48 m long, clear of node 2's crosswalk.

Three stations stand on the outer side of the map, each with one bay in front of it
for its vehicle (STATIONS): a hospital and a fire station on the west street, a
police station on the north street. Their bays are on streets the staged scenarios
do not park on, and are none of the bays tests/test_parking.py parks in.
"""
from __future__ import annotations

import math

import networkx as nx

from twin.engine.flood import FloodZone
from twin.engine.stations import Station
from twin.engine.street_profile import SIDEWALK_WIDTH_M, kerb_offset

BLOCK_M = 80.0          # centreline-to-centreline street spacing
SPEED_KPH = 40.0
LANES_PER_DIRECTION = 1

NODES = {
    1: (0.0, 0.0), 2: (BLOCK_M, 0.0), 3: (2 * BLOCK_M, 0.0),
    4: (0.0, BLOCK_M), 5: (BLOCK_M, BLOCK_M), 6: (2 * BLOCK_M, BLOCK_M),
}
STREETS = [(1, 2), (2, 3), (4, 5), (5, 6), (1, 4), (2, 5), (3, 6)]


def build_two_blocks_graph() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph(crs="local-metres")
    for node_id, (x, y) in NODES.items():
        g.add_node(node_id, x=x, y=y)
    for a, b in STREETS:
        for u, v in ((a, b), (b, a)):
            (ux, uy), (vx, vy) = NODES[u], NODES[v]
            length = math.hypot(vx - ux, vy - uy)
            g.add_edge(
                u, v,
                length=length,
                lanes=LANES_PER_DIRECTION,
                oneway=False,
                highway="residential",
                speed_kph=SPEED_KPH,
                travel_time=length / (SPEED_KPH / 3.6),
            )
    return g


# bays are parking spot ids "<u>_<v>_<index>" (app/parking.py): the right-hand kerb of u -> v
STATIONS = [
    Station(id="hospital", kind="hospital", label="Hospital", spot_ids=("4_1_1",)),            # west of x = 0, y = 51
    Station(id="fire_station", kind="fire_station", label="Fire station", spot_ids=("4_1_3",)),  # west of x = 0, y = 27
    Station(id="police_station", kind="police_station", label="Police station", spot_ids=("6_5_2",)),  # north of y = 80, x = 119
]


# the dip of street 2-3 (see the module docstring); the pump is the drainage pump at its low point
FLOOD_DIP = {"id": "dip-2-3", "street": (2, 3), "centre_s": 38.0, "half_length_m": 24.0, "dip_depth_m": 0.5,
             "catchment_m2": 80_000.0, "pump_id": "pump-2-3"}
DRAIN_CENTRE_S = 40.0  # the other streets: a drain at mid-street, its dip clear of the crosswalks at both ends


def _flood_dips() -> list[dict]:
    """A low point with a storm drain in every street. dip-2-3 comes first: the flood scenario's."""
    dips = [FLOOD_DIP]
    for u, v in STREETS:
        if (u, v) != FLOOD_DIP["street"]:
            dips.append({**FLOOD_DIP, "id": f"dip-{u}-{v}", "street": (u, v), "centre_s": DRAIN_CENTRE_S, "pump_id": f"pump-{u}-{v}"})
    return dips


def flood_zones(graph: nx.MultiDiGraph) -> list[FloodZone]:
    """The map's flood zones, one per street, dry. Rain over a zone (FloodZone.rain, or Simulation.rain
    over the whole city) is what fills them."""
    zones = []
    for dip in _flood_dips():
        u, v = dip["street"]
        a, b = graph.nodes[u], graph.nodes[v]
        spec = {k: val for k, val in dip.items() if k != "street"}
        zones.append(FloodZone(street=(u, v), ax=a["x"], ay=a["y"], bx=b["x"], by=b["y"],
                               road_half_width_m=kerb_offset(graph, u, v), sidewalk_width_m=SIDEWALK_WIDTH_M, **spec))
    return zones
