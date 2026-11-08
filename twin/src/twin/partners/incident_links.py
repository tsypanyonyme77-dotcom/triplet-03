"""A partner's incident ids and the Twin's call-centre incidents.

The City Brain numbers its own incidents (`inc-0001`, one per zone and type), so the incident_id in its
dispatch is not ours, even when it looks like one. The first time it names an incident, the link picks
our open incident it means, in this order of preference:
  1. in the zone the call names (the zone of the reading that opened the partner's incident),
  2. of the kind the unit is for (a fire truck to a fire, an ambulance or police car to an accident),
  3. not already linked to another partner incident,
  4. the oldest,
and keeps that pair for the rest of the run. A unit sent this way reports `unit_status` with the
partner's incident id (ours stays in `twin_incident_id`), which is how the partner closes its incident.
"""
from __future__ import annotations

from typing import Any

from twin.city.base import CitySource

UNIT_KIND_FITS = {"fire": "fire", "ambulance": "accident", "police": "accident"}


class IncidentLinks:
    def __init__(self, city: CitySource) -> None:
        self.city = city
        self._ours: dict[str, str] = {}                      # partner incident id -> our incident id
        self._units: dict[str, tuple[str, str]] = {}         # unit id -> (our incident id, partner incident id)

    def clear(self) -> None:
        """A new run: its incidents are new."""
        self._ours.clear()
        self._units.clear()

    def ours(self, partner_id: str) -> str | None:
        return self._ours.get(partner_id)

    def resolve(self, partner_id: str, zone_id: str | None, unit_type: str) -> str | None:
        """Our incident for a partner's, linking them on first use; None when the city has no open incident."""
        if partner_id in self._ours:
            return self._ours[partner_id]
        candidates = self.city.open_incidents()
        if not candidates:
            return None
        taken = set(self._ours.values())
        wanted = UNIT_KIND_FITS.get(unit_type)
        best = min(candidates, key=lambda i: (i["zone_id"] != zone_id, i["kind"] != wanted, i["incident_id"] in taken,
                                              i["first_call_t"]))
        self._ours[partner_id] = best["incident_id"]
        return best["incident_id"]

    def unit_sent(self, unit_id: str, partner_id: str) -> None:
        """A unit was dispatched (or found already dispatched) for a partner's incident."""
        ours = self._ours.get(partner_id)
        if ours is not None:
            self._units[unit_id] = (ours, partner_id)

    def partner_view(self, reading: dict[str, Any]) -> dict[str, Any]:
        """A unit_status reading as the partner that sent the unit knows it: its incident id, ours kept aside.
        Every other reading is returned unchanged."""
        if reading.get("type") != "unit_status":
            return reading
        value = reading["value"]
        link = self._units.get(value.get("unit_id"))
        if link is None or link[0] != value.get("incident_id"):
            return reading
        return {**reading, "value": {**value, "incident_id": link[1], "twin_incident_id": link[0]}}
