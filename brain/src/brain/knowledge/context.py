"""The city around an incident, as one small graph: the zones within a few hops, the nearest facility of each kind, the units out, the
other open incidents and what each sensor last said. It is read from the live graph and wraps the questions the team's tools already
ask; it adds no new source of truth. Nothing in it names a person: a unit's target and a sensor's readings are left out."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from brain.citygraph import MemoryGraphStore
from brain.contracts import Incident


class CtxNode(BaseModel):
    id: str  # `<kind>:<name>`
    kind: Literal["zone", "facility", "unit", "incident", "sensor"]
    label: str
    data: dict[str, Any] = Field(default_factory=dict)


class CtxEdge(BaseModel):
    from_id: str
    rel: str  # ADJACENT_TO, LOCATED_IN, NEAREST, ASSIGNED_TO, MONITORS: the names the Neo4j graph uses
    to_id: str


class ContextSubgraph(BaseModel):
    incident_id: str
    zone_id: str
    hops: int
    nodes: list[CtxNode]
    edges: list[CtxEdge]
    notes: list[str] = Field(default_factory=list)  # what is missing, in words


def city_context(store: MemoryGraphStore, incident: Incident, *, hops: int = 2) -> ContextSubgraph:
    here = incident.zone_id
    near = store.zones_within(here, hops)
    nodes: dict[str, CtxNode] = {}
    edges: dict[tuple[str, str, str], CtxEdge] = {}
    notes: list[str] = []

    def node(kind: str, ident: str, label: str, **data: Any) -> str:
        key = f"{kind}:{ident}"
        nodes.setdefault(key, CtxNode(id=key, kind=kind, label=label, data=data))  # type: ignore[arg-type]
        return key

    def edge(a: str, rel: str, b: str) -> None:
        edges.setdefault((a, rel, b), CtxEdge(from_id=a, rel=rel, to_id=b))

    def zone(zone_id: str) -> str:
        info = store.zones.nodes.get(zone_id, {})
        return node("zone", zone_id, info.get("name", zone_id), name=info.get("name", zone_id), hops=store.hop_distance(here, zone_id),
                    exit=zone_id in store.exits)

    for zone_id in sorted(near):
        zone(zone_id)
    for a, b in sorted(sorted(pair) for pair in store.zones.edges() if pair[0] in near and pair[1] in near):
        edge(zone(a), "ADJACENT_TO", zone(b))

    main = node("incident", incident.incident_id, f"{incident.type} in {store.zones.nodes.get(here, {}).get('name', here)}",
                type=incident.type, zone_id=here, status=incident.status)
    edge(main, "LOCATED_IN", zone(here))
    for other in sorted(store.g.nodes):
        if other[0] == "incident" and other[1] != incident.incident_id:
            found = store.g.nodes[other]["incident"]
            if found.status == "open" and found.zone_id in near:
                label = f"{found.type} in {store.zones.nodes.get(found.zone_id, {}).get('name', found.zone_id)}"
                edge(node("incident", found.incident_id, label, type=found.type, zone_id=found.zone_id, status=found.status), "LOCATED_IN", zone(found.zone_id))

    kinds = sorted({f["type"] for f in store.facilities()})
    for facility in store.facilities():
        if facility["zone_id"] in near:
            edge(node("facility", facility["id"], facility["id"], type=facility["type"], zone_id=facility["zone_id"], units=facility["units"],
                      available=facility["available"], quarantined=facility["quarantined"],
                      hops=store.hop_distance(here, facility["zone_id"])), "LOCATED_IN", zone(facility["zone_id"]))
    for kind in kinds:
        closest = store.nearest_facility(here, kind)
        if closest is None:
            notes.append(f"no {kind} can be reached from {here}")
            continue
        distance = store.hop_distance(here, closest["zone_id"])
        key = node("facility", closest["id"], closest["id"], type=kind, zone_id=closest["zone_id"], units=closest["units"],
                   available=closest["available"], quarantined=closest["quarantined"], hops=distance)
        edge(key, "LOCATED_IN", zone(closest["zone_id"]))
        edge(main, "NEAREST", key)
        if closest["zone_id"] not in near:
            notes.append(f"no {kind} within {hops} hops of {here}; the nearest is {closest['id']}, {distance} hops away")

    for unit in store.units_out():
        if unit.get("zone_id") in near:  # who a unit is chasing, and the gate key it was sent with, stay out
            key = node("unit", unit["unit_id"], unit["unit_id"], mode=unit.get("mode"), zone_id=unit.get("zone_id"), incident_id=unit.get("incident_id"))
            edge(key, "LOCATED_IN", zone(unit["zone_id"]))
            if unit.get("incident_id"):
                target = f"incident:{unit['incident_id']}"
                edge(key, "ASSIGNED_TO", target if target in nodes else node("incident", unit["incident_id"], unit["incident_id"]))
    for sensor in sorted(n for n in store.g.nodes if n[0] == "sensor"):
        attrs = store.g.nodes[sensor]
        if attrs.get("zone_id") in near:
            latest = max((r for r, _, key in store.g.in_edges(sensor, keys=True) if key == "REPORTED_BY"),
                         key=lambda r: store.g.nodes[r]["valid_at"], default=None)
            verdict = store.verdict_of(latest[1]) if latest else None
            key = node("sensor", sensor[1], sensor[1], type=attrs.get("type"), zone_id=attrs["zone_id"],
                       latest_verdict=verdict.status.value if verdict else None)
            edge(key, "MONITORS", zone(attrs["zone_id"]))
    if not any(n.kind == "sensor" for n in nodes.values()):
        notes.append(f"no sensor reports from within {hops} hops of {here}")
    return ContextSubgraph(incident_id=incident.incident_id, zone_id=here, hops=hops, nodes=list(nodes.values()), edges=list(edges.values()), notes=notes)
