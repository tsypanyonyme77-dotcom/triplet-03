"""Brain mock logic. Rule: act only on trusted verdicts; corroborate suspect; ignore untrusted/unknown."""

from __future__ import annotations

import json
import secrets
from typing import Any

import httpx

FLOOD_LEVEL_M = 1.2
VALVE_FOR_ZONE = {"zone-07": "valve-port-12", "zone-08": "valve-res-02"}


class BrainMock:
    def __init__(self, client: httpx.AsyncClient, api_key: str, scenario_id: str | None = None) -> None:
        self.client, self.api_key, self.scenario_id = client, api_key, scenario_id
        self.decisions: list[dict[str, Any]] = []

    @property
    def headers(self) -> dict[str, str]:
        h = {"X-API-Key": self.api_key}
        if self.scenario_id:
            h["X-Scenario-Id"] = self.scenario_id
        return h

    def note(self, what: str, **data: Any) -> dict[str, Any]:
        entry = {"brain": what, **data}
        self.decisions.append(entry)
        print(json.dumps(entry, default=str))
        return entry

    async def request_verdict(self, sensor_id: str, sequence_no: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"sensor_id": sensor_id}
        if sequence_no is not None:
            body["sequence_no"] = sequence_no
        try:
            r = await self.client.post("/v1/verdicts/request", json=body, headers=self.headers)
            r.raise_for_status()
            return dict(r.json())
        except (httpx.HTTPError, ValueError):
            # fail-safe rule from INTERFACE.md: Guardian unreachable → unknown
            return {"status": "unknown", "reasons": ["guardian_unreachable"], "verdict_id": None}

    async def latest_value(self, sensor_id: str) -> dict[str, Any] | None:
        r = await self.client.get(f"/v1/readings/{sensor_id}/latest", headers=self.headers)
        return r.json() if r.status_code == 200 else None

    async def send_call(self, actuator_id: str, action: str, params: dict[str, Any], *, zone_id: str | None,
                        trust_ref: str | None, justification: str, incident_id: str | None = None,
                        call_id: str | None = None) -> dict[str, Any]:
        call = {"call_id": call_id or f"call-{secrets.token_hex(4)}", "actuator_id": actuator_id, "action": action,
                "params": params, "zone_id": zone_id, "requesting_layer": "brain", "trust_ref": trust_ref,
                "justification": justification, "incident_id": incident_id}
        r = await self.client.post("/v1/actuator-calls", json=call, headers=self.headers)
        decision = r.json()
        self.note("call_sent", call=call, decision=decision)
        return dict(decision)

    async def check_flood(self, sensor_id: str, zone_id: str) -> dict[str, Any]:
        """Flood rule: close the zone valve only if the level verdict is trusted and above flood level."""
        v = await self.request_verdict(sensor_id)
        latest = await self.latest_value(sensor_id) or {}
        level = (latest.get("value") or {}).get("level_m")
        if v.get("status") != "trusted":
            return self.note("ignored", sensor_id=sensor_id, status=v.get("status"), reasons=v.get("reasons"),
                             would="corroborate" if v.get("status") == "suspect" else "nothing")
        if latest.get("rolled_back") or level is None or level <= FLOOD_LEVEL_M:
            return self.note("no_action", sensor_id=sensor_id, level_m=level)
        return await self.send_call(VALVE_FOR_ZONE[zone_id], "set_valve_state", {"state": "closed"},
                                    zone_id=zone_id, trust_ref=v["verdict_id"],
                                    justification=f"flood risk {zone_id}: {sensor_id}={level} m")

    async def check_fire_call(self, verdict: dict[str, Any], zone_id: str, incident_id: str) -> dict[str, Any]:
        if verdict.get("status") != "trusted":
            return self.note("ignored", verdict_id=verdict.get("verdict_id"), status=verdict.get("status"),
                             reasons=verdict.get("reasons"))
        return await self.send_call("dispatch-central", "dispatch_unit", {"unit_type": "fire"}, zone_id=zone_id,
                                    trust_ref=verdict["verdict_id"], justification=f"fire call {zone_id}",
                                    incident_id=incident_id)
