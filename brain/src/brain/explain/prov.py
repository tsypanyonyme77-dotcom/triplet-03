"""An explanation as W3C PROV-JSON: the same chain, in the standard a third party's tools read.

Every step of an explanation becomes an activity, every reading, verdict, decision and incident it names an entity, every layer an agent
(`twin`, `guardian`, `city_brain`). The relations are the PROV ones: `used`, `wasGeneratedBy`, `wasAssociatedWith`, `wasInformedBy`, `wasDerivedFrom`.
Nothing is added to what the explanation already says, so the same log gives the same bytes.
"""

from __future__ import annotations

import re
from typing import Any

from brain.explain.models import Explanation

PREFIXES = {"prov": "http://www.w3.org/ns/prov#", "xsd": "http://www.w3.org/2001/XMLSchema#", "brain": "https://city-brain.local/ns#"}
AGENTS = {"twin": "brain:twin", "guardian": "brain:guardian", "brain": "brain:city_brain"}


def _q(identifier: str) -> str:
    return "brain:" + re.sub(r"[^A-Za-z0-9._-]", "_", identifier)


def _kind(identifier: str) -> str:
    if "#" in identifier:
        return "reading"
    for prefix, kind in (("verdict", "verdict"), ("dec-", "decision"), ("inc-", "incident"), ("approval", "approval"), ("unit-", "unit")):
        if identifier.startswith(prefix):
            return kind
    return "other"


def to_prov(e: Explanation) -> dict[str, Any]:
    document: dict[str, Any] = {"prefix": dict(PREFIXES), "entity": {}, "activity": {}, "agent": {}, "wasGeneratedBy": {}, "used": {},
                                "wasAssociatedWith": {}, "wasDerivedFrom": {}, "wasInformedBy": {}}
    for layer, name in AGENTS.items():
        document["agent"][name] = {"prov:type": {"$": "prov:SoftwareAgent", "type": "prov:QUALIFIED_NAME"}, "brain:layer": layer}
    seen: set[str] = set()
    previous: str | None = None
    decision_activity: str | None = None
    relation = 0

    def link(table: str, **fields: str) -> None:
        nonlocal relation
        relation += 1
        document[table][f"_:{table[:3]}{relation}"] = fields

    for step in e.steps:
        activity = f"brain:step-{step.n}"
        document["activity"][activity] = {"prov:type": step.event_type, "brain:region": step.region, "brain:at_ms": step.at_ms, "brain:fact": step.fact, "brain:event": step.event_id}
        link("wasAssociatedWith", **{"prov:activity": activity, "prov:agent": AGENTS[step.layer]})
        if previous:
            link("wasInformedBy", **{"prov:informed": activity, "prov:informant": previous})
        for identifier in step.ids:
            entity = _q(identifier)
            if entity not in seen:
                seen.add(entity)
                document["entity"][entity] = {"prov:type": _kind(identifier), "brain:id": identifier}
                link("wasGeneratedBy", **{"prov:entity": entity, "prov:activity": activity})
            else:
                link("used", **{"prov:activity": activity, "prov:entity": entity})
        if step.event_type == "brain.decision.made":
            decision_activity = activity
        previous = activity
    gate = decision_activity or previous
    for cited in e.knowledge:
        entity = _q(cited.id)
        document["entity"].setdefault(entity, {"prov:type": "knowledge", "brain:id": cited.id, "prov:label": cited.title or cited.id, "brain:kind": cited.kind})
        if gate:
            link("used", **{"prov:activity": gate, "prov:entity": entity})
    subject = _q(e.id)
    if subject in document["entity"]:
        for entity, attrs in list(document["entity"].items()):
            if attrs.get("prov:type") == "reading":
                link("wasDerivedFrom", **{"prov:generatedEntity": subject, "prov:usedEntity": entity})
    if e.checks and gate:
        document["activity"][gate]["brain:gate_checks"] = [{"check": c.check, "passed": c.passed, "reason": c.reason} for c in e.checks]
    return document
