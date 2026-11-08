"""Effects: what the Brain's own actions are known to do to what it senses.

When the gate lets an action through and the Twin carries it out, this sink looks up whether the action has a declared
effect (a closed valve lowers the water level, a green signal clears a queue). If so it tells the forward models to
expect that change in that zone, for that window, so a change the Brain caused is followed and not doubted. A change in
another zone, outside the window or in the other direction is still a surprise. The table is empty until the Twin team
says what its actuators do; nothing here guesses.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from brain.citygraph import MemoryGraphStore
from brain.config import Effect
from brain.contracts import TimelineEvent
from brain.mind.forward import ForwardModels

FAILED = {"error", "rejected"}


class ActionEffects:
    """A timeline sink: it reads `brain.action.requested` and `brain.action.result` and never writes."""

    def __init__(self, effects: dict[str, Effect], store: MemoryGraphStore, forward: ForwardModels) -> None:
        self.effects, self.store, self.forward = effects, store, forward
        self._requested: dict[str, dict[str, Any]] = {}

    def write(self, event: TimelineEvent) -> None:
        if event.type == "brain.action.requested" and event.data.get("action") in self.effects:
            self._requested[event.data["decision_id"]] = {**event.data, "traceid": event.traceid}
        elif event.type == "brain.action.result" and event.data.get("decision_id") in self._requested:
            request = self._requested.pop(event.data["decision_id"])
            if event.data.get("status") not in FAILED:
                self._expect(request)

    def _zone_of(self, params: dict[str, Any]) -> str | None:
        if params.get("zone_id"):
            return params["zone_id"]
        for facility in self.store.topology().get("facilities", []):
            if facility.get("id") in (params.get("valve_id"), params.get("intersection_id"), params.get("breaker_id")):
                return facility.get("zone_id")
        return None

    def _expect(self, request: dict[str, Any]) -> None:
        effect = self.effects[request["action"]]
        zone = self._zone_of(request.get("params", {}))
        trigger = self.store.reading(str(request["traceid"]).replace(":", "#")) if request.get("traceid") else None
        if zone is None or trigger is None:
            return
        start = trigger.timestamp + timedelta(seconds=effect.delay_s)
        end = start + timedelta(seconds=effect.window_s)
        for field_name, direction in effect.changes.items():
            self.forward.expect(zone, effect.sensor_type, field_name, direction, start, end, request["action"])

    def close(self) -> None:
        pass
