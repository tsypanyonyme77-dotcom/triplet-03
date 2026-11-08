"""Graph algorithms for tactics: who can respond, where a suspect is likely to go, how to seal them in.

Pure functions over the city graph. They run on whatever topology the Twin provides,
zones at minimum.
"""

from __future__ import annotations

from typing import Any

import networkx as nx

from brain.citygraph import MemoryGraphStore

_SOURCE, _SINK = "__source__", "__exits__"


def nearest_units(store: MemoryGraphStore, zone_id: str, kind: str = "police_station", k: int = 3) -> list[dict[str, Any]]:
    """Stations of a kind that still have a unit, closest first."""
    ranked = []
    for facility in store.facilities(kind):
        distance = store.hop_distance(facility["zone_id"], zone_id)
        if distance is None or facility["quarantined"] or facility["available"] <= 0:
            continue
        ranked.append({
            "station_id": facility["id"], "actuator_id": facility.get("actuator_id"),
            "zone_id": facility["zone_id"], "hops": distance, "available_units": facility["available"],
        })
    return sorted(ranked, key=lambda u: (u["hops"], u["station_id"]))[:k]


def predict_escape(store: MemoryGraphStore, zone_id: str, heading_zone_id: str | None = None, top: int = 3) -> dict[str, Any]:
    """Where the suspect is likely to be next, assuming they make for a city exit.

    Each exit attracts in inverse proportion to its distance; that weight is shared among
    the first hops of the shortest paths to it. An observed heading adds weight to that neighbour.
    """
    graph = store.zones
    if zone_id not in graph:
        return {"at_exit": False, "next_zones": [], "note": f"{zone_id} is not in the topology"}
    if zone_id in store.exits:
        return {"at_exit": True, "next_zones": [], "note": f"{zone_id} is a city exit"}

    weights: dict[str, float] = {}
    for exit_zone in store.exits:
        try:
            paths = list(nx.all_shortest_paths(graph, zone_id, exit_zone))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        pull = 1.0 / len(paths[0])  # len(path) = hops + 1
        for path in paths:
            weights[path[1]] = weights.get(path[1], 0.0) + pull / len(paths)
    if heading_zone_id in graph.adj[zone_id]:
        weights[heading_zone_id] = weights.get(heading_zone_id, 0.0) + 0.5 * (sum(weights.values()) or 1.0)

    total = sum(weights.values())
    ranked = sorted(weights.items(), key=lambda item: (-item[1], item[0]))[:top]
    return {
        "at_exit": False,
        "next_zones": [{"zone_id": zone, "probability": round(weight / total, 3)} for zone, weight in ranked],
        "note": "share of exit-seeking paths through each neighbouring zone",
    }


def expected_zones(store: MemoryGraphStore, zone_id: str, held_zones: list[str]) -> set[str]:
    """Where a suspect can be while a plan made from `zone_id` still holds.

    If the held zones cut them off from every exit, that is the sealed area and the held
    zones themselves. If they only cover a route, it is where the suspect was and the zones held.
    """
    graph, held = store.zones, set(held_zones)
    if zone_id not in graph or zone_id in held:
        return {zone_id} | held
    area = set(nx.node_connected_component(graph.subgraph(set(graph) - held), zone_id))
    if area & set(store.exits):
        area = {zone_id}
    return area | held


def containment_cut(store: MemoryGraphStore, zone_id: str, lead_hops: int = 0) -> dict[str, Any]:
    """The fewest zones that, if held, cut the suspect off from every city exit.

    A minimum vertex cut between the area the suspect may occupy (their zone plus
    `lead_hops` of travel) and the exits. `lead_hops=0` is the tight perimeter; a larger
    lead allows for the time units need to arrive, at the price of more units.
    """
    graph = store.zones
    if zone_id not in graph:
        return {"possible": False, "zones": [], "lead_hops": lead_hops, "reason": f"{zone_id} is not in the topology"}
    area = store.zones_within(zone_id, lead_hops)
    reachable_exits = sorted(area & set(store.exits))
    if reachable_exits:
        return {
            "possible": False, "zones": [], "lead_hops": lead_hops,
            "reason": f"the suspect may already be at an exit ({', '.join(reachable_exits)})",
        }

    outside = graph.subgraph(set(graph) - area).copy()
    boundary = {n for zone in area for n in graph.adj[zone]} - area
    outside.add_edges_from((_SOURCE, zone) for zone in boundary)
    outside.add_edges_from((exit_zone, _SINK) for exit_zone in store.exits if exit_zone in outside)
    if _SINK not in outside or not nx.has_path(outside, _SOURCE, _SINK):
        return {"possible": True, "zones": [], "lead_hops": lead_hops, "reason": "no route to an exit; nothing to seal"}

    cut = sorted(nx.minimum_node_cut(outside, _SOURCE, _SINK))
    return {
        "possible": True, "zones": cut, "lead_hops": lead_hops,
        "reason": f"holding {len(cut)} zone{'' if len(cut) == 1 else 's'} separates {sorted(area)} from exits {store.exits}",
    }
