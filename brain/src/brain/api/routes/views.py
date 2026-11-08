"""Read-only views of what the Brain holds: the city, incidents, decisions, and the contract schemas."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from brain import config
from brain.knowledge.communities import communities, search_global
from brain.knowledge.context import city_context
from brain.knowledge.graph import build_graph
from brain.runtime import BrainService

if TYPE_CHECKING:
    from brain.api import Hub


def register(app: FastAPI, hub: Hub, service: Callable[[], BrainService]) -> None:
    @app.get("/api/topology")
    def topology() -> dict[str, Any]:
        return service().store.topology()

    @app.get("/api/incidents")
    def incidents() -> dict[str, Any]:
        return {"incidents": [incident.model_dump(mode="json") for incident in service().triage.incidents.values()]}

    @app.get("/api/incidents/{incident_id}/graph")
    def incident_graph(incident_id: str) -> dict[str, Any]:
        graph = service().store.incident_subgraph(incident_id)
        if not graph["nodes"]:
            raise HTTPException(404, f"unknown incident {incident_id}")
        return graph

    @app.get("/api/knowledge/global")
    def knowledge_global(question: str = Query(..., min_length=3), k: int = Query(2, ge=1, le=4)) -> dict[str, Any]:
        """A question about a whole area ("what can the Brain do about flooding, and what is blocked?"): the groups of procedures that
        answer it, each with a summary written by code from the playbooks and the gate's own policy."""
        kb = service().kb
        playbooks = [item for item in kb.items.values() if item.kind == "playbook"]
        groups = communities(build_graph(playbooks), playbooks, impact=hub.policy.gate.impact)
        return {"question": question, "communities": [g.model_dump(mode="json") for g in search_global(question, groups, kb.embedder, k)]}

    @app.get("/api/incidents/{incident_id}/context")
    def incident_context(incident_id: str, hops: int = Query(2, ge=0, le=6)) -> dict[str, Any]:
        """The city around an incident: zones, nearest facilities, units out, other incidents, sensors. Read live, no identities."""
        incident = service().store.incident(incident_id)
        if incident is None:
            raise HTTPException(404, f"unknown incident {incident_id}")
        return city_context(service().store, incident, hops=hops).model_dump(mode="json")

    @app.get("/api/decisions/{decision_id}")
    def decision(decision_id: str) -> dict[str, Any]:
        provenance = service().store.provenance(decision_id)
        if not provenance:
            raise HTTPException(404, f"unknown decision {decision_id}")
        store = service().store
        provenance["readings"] = [
            {"reading_id": reading_id, "type": reading.type, "zone_id": reading.zone_id,
             "timestamp": reading.timestamp.isoformat(), "verdict": verdict.status.value if verdict else None,
             "verdict_id": verdict.verdict_id if verdict else None}
            for reading_id in provenance["readings"]
            if (reading := store.reading(reading_id)) is not None
            for verdict in [store.verdict_of(reading_id)]
        ]
        return provenance

    @app.get("/schemas")
    def schemas() -> dict[str, list[str]]:
        folder = config.home() / "contracts" / "schemas"
        return {"schemas": sorted(path.name.removesuffix(".schema.json") for path in folder.glob("*.schema.json"))}

    @app.get("/schemas/{name}")
    def schema(name: str) -> JSONResponse:
        path = config.home() / "contracts" / "schemas" / f"{Path(name).name}.schema.json"
        if not re.fullmatch(r"[A-Za-z0-9_]{1,60}", name) or not path.exists():
            raise HTTPException(404, f"no schema named {name}")
        return JSONResponse(json.loads(path.read_text()))
