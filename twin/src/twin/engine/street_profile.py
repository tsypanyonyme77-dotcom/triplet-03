"""Street cross-section: where lanes, parking, kerb and sidewalk sit, measured
sideways from a street's centreline. One source of truth for cars, parking,
pedestrians, crosswalks and the viewers.

For one direction of travel (offsets grow to the right of travel):

    centreline | driving lanes | parking lane | kerb | sidewalk | building line
               0          driving_outer      kerb_offset     kerb + SIDEWALK

On a two-way street each direction's lanes sit on its own side of the centreline
(sim._update_xy pushes them out by half their block width); a one-way street's
lanes are centred on the centreline.
"""
from __future__ import annotations

import networkx as nx

from twin.engine.road_network import LANE_WIDTH_M

PARKING_LANE_M = 3.0
SIDEWALK_WIDTH_M = 4.0
CROSSWALK_WIDTH_M = 3.0
STOP_LINE_GAP_M = 1.0       # stop line sits this far before the crosswalk


def _edge(graph: nx.MultiDiGraph, u: int, v: int) -> dict:
    data = graph.get_edge_data(u, v)
    if not data:
        raise ValueError(f"no edge {u}->{v}")
    return data[0]


def is_oneway(graph: nx.MultiDiGraph, u: int, v: int) -> bool:
    return bool(_edge(graph, u, v).get("oneway")) or not graph.has_edge(v, u)


def driving_outer_offset(graph: nx.MultiDiGraph, u: int, v: int) -> float:
    """Outer edge of the driving lanes of edge u->v (right of travel)."""
    lanes = _edge(graph, u, v).get("lanes", 1)
    median = 0.0 if is_oneway(graph, u, v) else lanes / 2.0
    return (median + lanes / 2.0) * LANE_WIDTH_M


def parking_offset(graph: nx.MultiDiGraph, u: int, v: int) -> float:
    """Centre of a parked car on the right of u->v."""
    return driving_outer_offset(graph, u, v) + PARKING_LANE_M / 2.0


def kerb_offset(graph: nx.MultiDiGraph, u: int, v: int) -> float:
    return driving_outer_offset(graph, u, v) + PARKING_LANE_M


def sidewalk_centre_offset(graph: nx.MultiDiGraph, u: int, v: int) -> float:
    """Centreline of the sidewalk on the right of travel u->v."""
    return kerb_offset(graph, u, v) + SIDEWALK_WIDTH_M / 2.0


def right_sidewalk_offset(graph: nx.MultiDiGraph, u: int, v: int) -> float:
    """Sidewalk centre on the right of u->v, also for a one-way street walked against
    its direction (u->v missing): a one-way cross-section is symmetric."""
    if graph.has_edge(u, v):
        return sidewalk_centre_offset(graph, u, v)
    return sidewalk_centre_offset(graph, v, u)
