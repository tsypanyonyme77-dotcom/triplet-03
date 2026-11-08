"""Road network loading from OpenStreetMap, projected to local planar coords.

Caches the graph to disk so repeated runs (and demos) don't hit the OSM API.
"""
from __future__ import annotations

import pathlib

import networkx as nx

CACHE_DIR = pathlib.Path(__file__).parent / "data"

# Downtown, denser arterial roads with real multi-lane tags, better for lane-change demo.
DEFAULT_PLACE = "Avenue Habib Bourguiba, Tunis, Tunisia"
DEFAULT_DIST_M = 1200

# fallback speeds (kph) by OSM highway class, used only when maxspeed is untagged
HWY_SPEED_FALLBACK = {
    "motorway": 90,
    "trunk": 70,
    "primary": 60,
    "secondary": 50,
    "tertiary": 40,
    "residential": 30,
    "living_street": 15,
    "unclassified": 30,
}
DEFAULT_SPEED_FALLBACK = 30

# default lane count by highway class, used only when OSM 'lanes' tag is missing
HWY_LANES_FALLBACK = {
    "motorway": 2,
    "trunk": 2,
    "primary": 2,
    "secondary": 2,
    "tertiary": 1,
    "residential": 1,
    "living_street": 1,
    "unclassified": 1,
}
DEFAULT_LANES_FALLBACK = 1
LANE_WIDTH_M = 5.0


def _cache_path(place: str) -> pathlib.Path:
    slug = place.lower().replace(",", "").replace(" ", "_")
    return CACHE_DIR / f"{slug}.graphml"


def _first(value):
    """OSM tags are sometimes a list (multiple tagged values on a way segment)."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _add_lane_counts(g: nx.MultiDiGraph) -> None:
    """Set per-direction lane count and width on each directed edge.

    OSM's `lanes` tag on a two-way street counts lanes in BOTH directions
    combined (e.g. lanes=2 means 1 each way), but this graph stores each
    direction as a separate directed edge. Without splitting, both directions
    render their full lane count centered on the same line -> cars driving
    opposite ways end up drawn on top of each other. When a reverse edge
    exists, we halve the tagged count (min 1 lane) to get this direction's
    share; true one-way edges (no reverse counterpart) keep the full count.
    """
    for u, v, data in g.edges(data=True):
        highway = _first(data.get("highway")) or "unclassified"
        lanes_tag = _first(data.get("lanes"))
        try:
            tagged_lanes = int(lanes_tag) if lanes_tag is not None else None
        except (TypeError, ValueError):
            tagged_lanes = None
        if tagged_lanes is None or tagged_lanes < 1:
            tagged_lanes = HWY_LANES_FALLBACK.get(highway, DEFAULT_LANES_FALLBACK)

        is_oneway = bool(data.get("oneway")) or not g.has_edge(v, u)
        lanes = tagged_lanes if is_oneway else max(1, tagged_lanes // 2)

        data["lanes"] = lanes
        data["width"] = lanes * LANE_WIDTH_M


def load_road_graph(place: str = DEFAULT_PLACE, dist_m: int = DEFAULT_DIST_M) -> nx.MultiDiGraph:
    """Load a drivable street graph, projected to metric coordinates (meters).

    Node attrs: x, y (meters, local projection)
    Edge attrs: length (meters), speed_kph, lanes, width (meters), oneway
    """
    import osmnx as ox  # noqa: PLC0415 (optional, `--group osm`: the two-block map does not need it)

    cache_file = _cache_path(place)
    if cache_file.exists():
        g = ox.load_graphml(
            cache_file,
            edge_dtypes={
                "length": float,
                "speed_kph": float,
                "travel_time": float,
                "lanes": int,
                "width": float,
                "oneway": lambda v: v == "True",
                "reversed": lambda v: v == "True",
            },
        )
        return g

    try:
        g = ox.graph_from_address(place, dist=dist_m, network_type="drive")
    except Exception:
        # Fallback to a fixed point if geocoding fails (e.g. no network at build time)
        g = ox.graph_from_point((36.8460, 10.1900), dist=dist_m, network_type="drive")

    g = ox.routing.add_edge_speeds(g, hwy_speeds=HWY_SPEED_FALLBACK, fallback=DEFAULT_SPEED_FALLBACK)
    g = ox.routing.add_edge_travel_times(g)
    g = ox.project_graph(g)  # -> meters, local UTM
    _add_lane_counts(g)

    CACHE_DIR.mkdir(exist_ok=True)
    ox.save_graphml(g, cache_file)
    return g


def graph_summary(g: nx.MultiDiGraph) -> dict:
    xs = [d["x"] for _, d in g.nodes(data=True)]
    ys = [d["y"] for _, d in g.nodes(data=True)]
    return {
        "num_nodes": g.number_of_nodes(),
        "num_edges": g.number_of_edges(),
        "bounds": {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)},
    }
