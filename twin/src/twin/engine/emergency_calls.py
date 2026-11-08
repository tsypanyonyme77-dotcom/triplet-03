"""The emergency call centre of the simulated city: numbers calls and merges them into incidents.

Several witnesses of one crash make several calls. The centre does not know the truth;
it merges a call into an open incident when the reported location is within
MERGE_RADIUS_M of the incident's first report and the call comes at most MERGE_WINDOW_S
after the incident's latest call. Otherwise the call opens a new incident. A false
report therefore gets its own incident id, unless it happens to be near a real one.

Each call keeps its ground truth (`truth_accident_id`, None for a false report) for the
Twin's own logs and tests; the Twin never emits it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

MERGE_RADIUS_M = 50.0
MERGE_WINDOW_S = 300.0


@dataclass
class CallCentre:
    calls: list[dict] = field(default_factory=list)
    incidents: list[dict] = field(default_factory=list)

    def receive(self, t: float, reporter_id: str, reporter_kind: str, said: dict, truth_accident_id: str | None) -> dict:
        incident = self._match(t, said["x"], said["y"])
        if incident is None:
            incident = {"id": f"inc-{len(self.incidents) + 1:04d}", "x": said["x"], "y": said["y"],
                        "first_call_t": round(t, 2), "last_call_t": round(t, 2), "call_ids": []}
            self.incidents.append(incident)
        call = {"call_id": f"call-{len(self.calls) + 1:04d}", "incident_id": incident["id"], "t": round(t, 2),
                "reporter_id": reporter_id, "reporter_kind": reporter_kind, **said,
                "truth_accident_id": truth_accident_id}
        incident["call_ids"].append(call["call_id"])
        incident["last_call_t"] = round(t, 2)
        self.calls.append(call)
        return call

    def alert(self, t: float, x: float, y: float) -> dict:
        """A camera alert: joins the open incident at (x, y) or opens one, without a call."""
        incident = self._match(t, x, y)
        if incident is None:
            incident = {"id": f"inc-{len(self.incidents) + 1:04d}", "x": round(x, 1), "y": round(y, 1),
                        "first_call_t": round(t, 2), "last_call_t": round(t, 2), "call_ids": []}
            self.incidents.append(incident)
        return incident

    def incident(self, incident_id: str) -> dict | None:
        return next((i for i in self.incidents if i["id"] == incident_id), None)

    def _match(self, t: float, x: float, y: float) -> dict | None:
        best, best_d = None, MERGE_RADIUS_M
        for inc in self.incidents:
            if t - inc["last_call_t"] > MERGE_WINDOW_S:
                continue
            d = math.hypot(inc["x"] - x, inc["y"] - y)
            if d <= best_d:
                best, best_d = inc, d
        return best
