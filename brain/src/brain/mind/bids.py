"""Bids: how well a pack can answer an incident, given what the Twin really offers right now.

A pack scores its fit for the incident type, scaled down by the share of the actuators it needs that the
Twin exposes, and again when it has no free unit to send. Bids explain who the workspace would recruit and
say early when nobody can answer; they never stop a reflex rule, which the gate checks anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

from brain.citygraph import MemoryGraphStore
from brain.contracts import Incident
from brain.departments import Manifest
from brain.graph.actuation import UNIT_FACILITY

NO_UNIT_FACTOR = 0.3


@dataclass(frozen=True)
class PackBid:
    pack: str
    score: float
    reason: str


def _needs(pack: Manifest) -> list[str]:
    return pack.needs or sorted({actuator.split(":")[0] for actuator in pack.actuators})


def bid(pack: Manifest, incident: Incident, capabilities: set[str], store: MemoryGraphStore) -> PackBid:
    rule = next((b for b in pack.bids if b.incident == incident.type), None)
    weight = (rule.weight if rule else 0.0) if pack.bids else float(incident.type in pack.incident_types)
    if weight <= 0:
        return PackBid(pack.code, 0.0, f"incident type {incident.type} is not this pack's")

    needs = _needs(pack)
    missing = [name for name in needs if name not in capabilities]
    capable = 1 - len(missing) / len(needs) if needs else 1.0
    if capable < 1:
        reason = f"the Twin has no {', '.join(missing)}"
    else:
        reason = f"answers {incident.type}"

    unit_types = [rule.unit] if rule and rule.unit else sorted({a.split(":")[1] for a in pack.actuators if a.startswith("dispatch_unit:")})
    units = 1.0
    if unit_types and "dispatch_unit" in capabilities:
        free = any(store.nearest_facility(incident.zone_id, UNIT_FACILITY[t], need_unit=True) for t in unit_types if t in UNIT_FACILITY)
        if not free:
            units, reason = NO_UNIT_FACTOR, f"no free {' or '.join(unit_types)} unit"
    return PackBid(pack.code, round(weight * capable * units, 2), reason)
