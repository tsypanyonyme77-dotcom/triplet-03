"""The City Graph: topology, live state and provenance in one graph.

`MemoryGraphStore` (NetworkX) is what the decision path reads: it never waits on a
database. `brain.citygraph.neo4j.MirroredGraphStore` extends it and copies every write
to Neo4j, which holds the durable graph and the knowledge index.

Node keys are `(kind, id)` tuples. Edge labels follow the spec:
ADJACENT_TO, LOCATED_IN, MONITORS, REPORTED_BY, OBSERVED_AT, VERIFIED_BY, PRESENT_AT,
EVIDENCE_FOR, AT_SCENE, HANDLED_BY, CITES, ISSUED.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import networkx as nx

from brain.contracts import (
    CitizenActivity,
    Incident,
    ProposedAction,
    SensorReading,
    TrustVerdict,
    VerdictStatus,
)

Node = tuple[str, str]


@dataclass(frozen=True)
class Sighting:
    reading_id: str
    time: datetime
    zone_id: str
    speed_kmh: float
    activity: str
    heading_zone_id: str | None


class MemoryGraphStore:
    def __init__(self) -> None:
        self.g = nx.MultiDiGraph()
        self.zones = nx.Graph()  # undirected adjacency, for path algorithms
        self.exits: list[str] = []
        self.latest_at: datetime | None = None  # time of the newest reading: the Brain's clock for evidence
        self._sightings: dict[str, list[Sighting]] = {}
        self._facilities: dict[str, dict[str, Any]] = {}
        self._units: dict[str, dict[str, Any]] = {}  # units out on a dispatch, by unit id
        # Set by the service when state is kept on disk: called with every append-only fact.
        self.journal: Callable[[str, dict[str, Any]], None] | None = None

    # ------------------------------------------------------------------ persistence

    def _record(self, kind: str, payload: dict[str, Any]) -> None:
        if self.journal is not None:
            self.journal(kind, payload)

    def replay(self, kind: str, payload: dict[str, Any]) -> None:
        """Apply one journalled fact again after a restart, without journalling or mirroring it a second time."""
        base = MemoryGraphStore
        if kind == "reading":
            reading = SensorReading.model_validate(payload["reading"])
            base.add_reading(self, reading, TrustVerdict.model_validate(payload["verdict"]))
            if reading.type == "citizen_activity":
                base.add_sighting(self, reading, CitizenActivity.model_validate(reading.value))
        elif kind == "retract":
            base.retract_verdict(self, payload["reading_id"], payload["reason"])
        elif kind == "at_scene":
            base.mark_at_scene(self, payload["entity_id"], payload["incident_id"])
        elif kind == "decision":
            base.add_decision(self, payload["decision_id"], ProposedAction.model_validate(payload["proposal"]), payload["config_hash"])
        elif kind == "action":
            base.add_action(self, payload["decision_id"], payload["action_id"], payload["call"], payload["result"])

    def snapshot(self) -> dict[str, Any]:
        """The mutable part of the graph: which units are out and which stations are quarantined."""
        return {
            "units": list(self._units.values()),
            "quarantined": sorted(f["actuator_id"] for f in self._facilities.values() if f["quarantined"] and f.get("actuator_id")),
        }

    def restore(self, saved: dict[str, Any]) -> None:
        for unit in saved.get("units", []):
            MemoryGraphStore.commit_unit(self, unit["actuator_id"], unit["unit_id"],
                                         **{k: v for k, v in unit.items() if k not in ("actuator_id", "unit_id")})
        for actuator_id in saved.get("quarantined", []):
            MemoryGraphStore.mark_quarantined(self, actuator_id)

    # ------------------------------------------------------------------ topology

    def load_topology(self, topology: dict[str, Any]) -> None:
        for zone in topology.get("zones", []):
            self.zones.add_node(zone["id"], **zone)
            self.g.add_node(("zone", zone["id"]), **zone)
        for a, b in topology.get("adjacency", []):
            self.zones.add_edge(a, b)
            self.g.add_edge(("zone", a), ("zone", b), key="ADJACENT_TO")
            self.g.add_edge(("zone", b), ("zone", a), key="ADJACENT_TO")
        self.exits = list(topology.get("exits", []))
        for facility in topology.get("facilities", []):
            record = {"units": 2, **facility, "committed": 0, "quarantined": False}
            self._facilities[facility["id"]] = record
            self.g.add_node(("facility", facility["id"]), **facility)
            self.g.add_edge(("facility", facility["id"]), ("zone", facility["zone_id"]), key="LOCATED_IN")
        for sensor in topology.get("sensors", []):
            self.g.add_node(("sensor", sensor["id"]), **sensor)
            self.g.add_edge(("sensor", sensor["id"]), ("zone", sensor["zone_id"]), key="MONITORS")

    def topology(self) -> dict[str, Any]:
        return {
            "zones": [dict(attrs) for _, attrs in self.zones.nodes(data=True)],
            "adjacency": [list(edge) for edge in self.zones.edges()],
            "exits": self.exits,
            "facilities": [self._public(f) for f in self._facilities.values()],
        }

    def hop_distance(self, a: str, b: str) -> int | None:
        if a == b:
            return 0
        try:
            return nx.shortest_path_length(self.zones, a, b)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def zones_within(self, zone_id: str, hops: int) -> set[str]:
        if zone_id not in self.zones:
            return {zone_id}
        return set(nx.single_source_shortest_path_length(self.zones, zone_id, cutoff=hops))

    # ------------------------------------------------------------------ facilities and units

    @staticmethod
    def _public(facility: dict[str, Any]) -> dict[str, Any]:
        return {**facility, "available": max(facility["units"] - facility["committed"], 0)}

    def facilities(self, kind: str | None = None) -> list[dict[str, Any]]:
        return [self._public(f) for f in self._facilities.values() if kind is None or f["type"] == kind]

    def nearest_facility(
        self, zone_id: str, kind: str, need_unit: bool = False, reserved: dict[str, int] | None = None
    ) -> dict[str, Any] | None:
        """Closest usable facility of a kind. `reserved` counts units promised earlier in the same plan."""
        reserved = reserved or {}
        candidates = []
        for facility in self._facilities.values():
            if facility["type"] != kind or facility["quarantined"]:
                continue
            free = facility["units"] - facility["committed"] - reserved.get(facility["id"], 0)
            distance = self.hop_distance(facility["zone_id"], zone_id)
            if distance is None or (need_unit and free <= 0):
                continue
            candidates.append((distance, facility["id"]))
        return self._public(self._facilities[min(candidates)[1]]) if candidates else None

    def _by_actuator(self, actuator_id: str) -> dict[str, Any] | None:
        return next((f for f in self._facilities.values() if f.get("actuator_id") == actuator_id), None)

    def commit_unit(self, actuator_id: str, unit_id: str | None = None, **details: Any) -> None:
        """A unit left this station. `details` (incident, mode, zone, target, gate key) let it be recalled."""
        if unit_id is not None:
            if unit_id in self._units:
                return  # already on the books, e.g. the Twin answered a repeated call with `duplicate`
            self._units[unit_id] = {"unit_id": unit_id, "actuator_id": actuator_id, **details}
        facility = self._by_actuator(actuator_id)
        if facility is not None:
            facility["committed"] += 1

    def units_out(self, incident_id: str | None = None, mode: str | None = None) -> list[dict[str, Any]]:
        return [
            dict(unit) for unit in self._units.values()
            if (incident_id is None or unit.get("incident_id") == incident_id) and (mode is None or unit.get("mode") == mode)
        ]

    def release_unit(self, unit_id: str) -> dict[str, Any] | None:
        """The unit is back at its station. Returns its record, or None if it was not out."""
        unit = self._units.pop(unit_id, None)
        if unit is None:
            return None
        facility = self._by_actuator(unit["actuator_id"])
        if facility is not None and facility["committed"] > 0:
            facility["committed"] -= 1
        return unit

    def mark_quarantined(self, actuator_id: str) -> None:
        facility = self._by_actuator(actuator_id)
        if facility is not None:
            facility["quarantined"] = True

    # ------------------------------------------------------------------ live state

    def add_reading(self, reading: SensorReading, verdict: TrustVerdict) -> None:
        node: Node = ("reading", reading.reading_id)
        if self.latest_at is None or reading.timestamp > self.latest_at:
            self.latest_at = reading.timestamp
        self._record("reading", {"reading": reading.model_dump(mode="json"), "verdict": verdict.model_dump(mode="json")})
        self.g.add_node(node, reading=reading, valid_at=reading.timestamp, invalid_at=None)
        self.g.add_node(("verdict", verdict.verdict_id), verdict=verdict)
        self.g.add_edge(node, ("verdict", verdict.verdict_id), key="VERIFIED_BY")
        self.g.add_edge(node, ("sensor", reading.sensor_id), key="REPORTED_BY")
        self.g.add_edge(node, ("zone", reading.zone_id), key="OBSERVED_AT")

    def add_sighting(self, reading: SensorReading, value: CitizenActivity) -> Sighting:
        sighting = Sighting(
            reading_id=reading.reading_id,
            time=reading.timestamp,
            zone_id=value.zone_id or reading.zone_id,
            speed_kmh=value.speed_kmh,
            activity=value.activity,
            heading_zone_id=value.heading_zone_id,
        )
        seen = self._sightings.setdefault(value.citizen_id, [])
        if any(s.reading_id == sighting.reading_id for s in seen):
            return sighting  # the same reading handled twice, after a restart
        seen.append(sighting)
        seen.sort(key=lambda s: s.time)
        self.g.add_node(("entity", value.citizen_id), kind="citizen")
        self.g.add_edge(
            ("entity", value.citizen_id),
            ("zone", sighting.zone_id),
            key=f"PRESENT_AT:{reading.reading_id}",
            at=reading.timestamp,
        )
        return sighting

    def sightings(self, entity_id: str) -> list[Sighting]:
        return list(self._sightings.get(entity_id, []))

    def entities_seen(self, zones: set[str], start: datetime, end: datetime) -> list[str]:
        return sorted(
            entity
            for entity, seen in self._sightings.items()
            if any(s.zone_id in zones and start <= s.time <= end for s in seen)
        )

    def reading(self, reading_id: str) -> SensorReading | None:
        attrs = self.g.nodes.get(("reading", reading_id))
        return attrs["reading"] if attrs else None

    def verdict_of(self, reading_id: str) -> TrustVerdict | None:
        node: Node = ("reading", reading_id)
        if node not in self.g:
            return None
        for _, target, key in self.g.out_edges(node, keys=True):
            if key == "VERIFIED_BY":
                return self.g.nodes[target]["verdict"]
        return None

    def retract_verdict(self, reading_id: str, reason: str) -> TrustVerdict | None:
        """The Guardian takes its verdict back. The same verdict id now reads `untrusted`, so every later check that follows it refuses."""
        node: Node = ("reading", reading_id)
        if node not in self.g:
            return None
        verdict = self.verdict_of(reading_id)
        if verdict is None:
            return None
        self._record("retract", {"reading_id": reading_id, "reason": reason})
        revised = verdict.model_copy(update={"status": VerdictStatus.UNTRUSTED, "confidence": 0.0,
                                             "reasons": [*verdict.reasons, f"retracted: {reason}"]})
        self.g.nodes[("verdict", verdict.verdict_id)]["verdict"] = revised
        return revised

    def verdict(self, verdict_id: str) -> TrustVerdict | None:
        attrs = self.g.nodes.get(("verdict", verdict_id))
        return attrs["verdict"] if attrs else None

    # ------------------------------------------------------------------ provenance

    def add_incident(self, incident: Incident) -> None:
        self.g.add_node(("incident", incident.incident_id), incident=incident)

    def incident(self, incident_id: str) -> Incident | None:
        attrs = self.g.nodes.get(("incident", incident_id))
        return attrs["incident"] if attrs else None

    def close_incident(self, incident: Incident) -> None:
        """The Incident object is shared with triage; this hook exists for the mirror."""

    def link_evidence(self, reading_id: str, incident_id: str) -> None:
        self.g.add_edge(("reading", reading_id), ("incident", incident_id), key="EVIDENCE_FOR")

    def mark_at_scene(self, entity_id: str, incident_id: str) -> None:
        if not self.g.has_edge(("entity", entity_id), ("incident", incident_id), key="AT_SCENE"):
            self._record("at_scene", {"entity_id": entity_id, "incident_id": incident_id})
        self.g.add_edge(("entity", entity_id), ("incident", incident_id), key="AT_SCENE")

    def scenes_attended(self, entity_id: str) -> set[str]:
        node: Node = ("entity", entity_id)
        if node not in self.g:
            return set()
        return {t[1] for _, t, key in self.g.out_edges(node, keys=True) if key == "AT_SCENE"}

    def add_decision(self, decision_id: str, proposal: ProposedAction, config_hash: str) -> None:
        node: Node = ("decision", decision_id)
        self._record("decision", {"decision_id": decision_id, "proposal": proposal.model_dump(mode="json"), "config_hash": config_hash})
        self.g.add_node(node, proposal=proposal, config_hash=config_hash)
        self.g.add_edge(("incident", proposal.incident_id), node, key="HANDLED_BY")
        for reading_id in proposal.evidence_reading_ids:
            self.g.add_edge(node, ("reading", reading_id), key="CITES")
        if proposal.trust_ref:
            self.g.add_edge(node, ("verdict", proposal.trust_ref), key="CITES")
        for knowledge_id in proposal.knowledge_citations:
            self.g.add_node(("knowledge", knowledge_id))
            self.g.add_edge(node, ("knowledge", knowledge_id), key="CITES")

    def add_action(self, decision_id: str, action_id: str, call: dict, result: dict) -> None:
        self._record("action", {"decision_id": decision_id, "action_id": action_id, "call": call, "result": result})
        self.g.add_node(("action", action_id), call=call, result=result)
        self.g.add_edge(("decision", decision_id), ("action", action_id), key="ISSUED")

    def _targets(self, node: Node, label: str) -> list[Node]:
        return [t for _, t, key in self.g.out_edges(node, keys=True) if key == label]

    def provenance(self, decision_id: str) -> dict[str, Any]:
        """The subgraph that explains one decision: what it cited and what it caused."""
        node: Node = ("decision", decision_id)
        if node not in self.g:
            return {}
        cited = self._targets(node, "CITES")
        proposal: ProposedAction = self.g.nodes[node]["proposal"]
        return {
            "decision_id": decision_id,
            "incident_id": proposal.incident_id,
            "department": proposal.department,
            "tier": proposal.tier,
            "action": proposal.action,
            "params": proposal.params,
            "justification": proposal.justification,
            "config_hash": self.g.nodes[node]["config_hash"],
            "readings": sorted(i for kind, i in cited if kind == "reading"),
            "verdicts": sorted(i for kind, i in cited if kind == "verdict"),
            "knowledge": sorted(i for kind, i in cited if kind == "knowledge"),
            "actions": [{"action_id": i, **self.g.nodes[("action", i)]} for _, i in self._targets(node, "ISSUED")],
        }

    def incident_subgraph(self, incident_id: str) -> dict[str, Any]:
        """Everything linked to one incident, as plain nodes and edges for a screen to draw."""
        root: Node = ("incident", incident_id)
        if root not in self.g:
            return {"nodes": [], "edges": []}
        nodes: dict[Node, dict[str, Any]] = {}
        edges: list[dict[str, str]] = []

        def add(node: Node, **attrs: Any) -> None:
            nodes.setdefault(node, {"id": f"{node[0]}:{node[1]}", "kind": node[0], "label": node[1], **attrs})

        def link(source: Node, target: Node, label: str) -> None:
            edges.append({"source": f"{source[0]}:{source[1]}", "target": f"{target[0]}:{target[1]}", "label": label})

        def add_reading(reading_node: Node) -> None:
            reading: SensorReading = self.g.nodes[reading_node]["reading"]
            add(reading_node, type=reading.type, zone_id=reading.zone_id)
            verdict = self.verdict_of(reading_node[1])
            if verdict is not None:
                verdict_node: Node = ("verdict", verdict.verdict_id)
                add(verdict_node, status=verdict.status.value)
                link(reading_node, verdict_node, "VERIFIED_BY")

        incident: Incident = self.g.nodes[root]["incident"]
        add(root, type=incident.type, zone_id=incident.zone_id, status=incident.status)
        for source, _, key in self.g.in_edges(root, keys=True):
            if key == "EVIDENCE_FOR":
                add_reading(source)
                link(source, root, key)
        for decision in self._targets(root, "HANDLED_BY"):
            proposal: ProposedAction = self.g.nodes[decision]["proposal"]
            add(decision, action=proposal.action, tier=proposal.tier, mode=proposal.params.get("mode"))
            link(root, decision, "HANDLED_BY")
            for cited in self._targets(decision, "CITES"):
                if cited[0] == "reading":
                    add_reading(cited)
                elif cited[0] == "knowledge":
                    add(cited)
                elif cited not in nodes:
                    continue
                link(decision, cited, "CITES")
            for action in self._targets(decision, "ISSUED"):
                add(action, status=self.g.nodes[action]["result"].get("status"))
                link(decision, action, "ISSUED")
        return {"nodes": list(nodes.values()), "edges": edges}
