"""`brain onboard`: propose how to read a Twin that names things differently, from a sample of what it sends.

The contract is fixed; a Twin's names and units are not. Perception already renames types (`twin.type_aliases`) and builds a field
from another (`twin.profiles`: `canonical = twin_field * scale + offset`), so a changed Twin is a config edit. This module looks at a
sample of readings and proposes that edit: which of its types is which of ours, which field is which, and the scale that turns
centimetres into metres or a percentage into a fraction. Every line carries a confidence and its evidence; under the floor it is marked
`review`; a type nothing fits is `unmapped`, never guessed. It never writes a file: a person reads the proposal and edits the config.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

FLOOR = 0.75  # at or above: proposed as is. Between ACCEPT and FLOOR: proposed, marked for review. Below ACCEPT: not proposed.
ACCEPT = 0.4

# What each contract type is called in the wild.
TYPE_WORDS = {
    "water_level": {"water", "level", "river", "gauge", "gage", "flood", "tide", "depth", "stage"},
    "traffic_camera": {"traffic", "camera", "cam", "vehicle", "vehicles", "car", "cars", "counter", "road", "congestion"},
    "power_load": {"power", "load", "grid", "electric", "energy", "substation", "feeder", "demand"},
    "air_quality": {"air", "quality", "aqi", "pollution", "smog", "particulate", "pm"},
}

# The required fields of each type, and the words a Twin might use for them: (our field, words, the unit our field is in).
FIELDS = {
    "water_level": [("level_m", {"level", "depth", "height", "stage"}, "length"), ("flow_rate_m3s", {"flow", "discharge", "rate"}, None)],
    "traffic_camera": [("congestion_score", {"congestion", "jam", "occupancy", "density"}, "fraction"), ("vehicle_count", {"vehicle", "vehicles", "car", "cars", "count"}, None),
                       ("avg_speed_kmh", {"speed", "velocity", "avg"}, None)],
    "power_load": [("load_kw", {"kw", "load", "power", "demand"}, "kw"), ("capacity_kw", {"cap", "capacity", "rated", "max"}, "kw"), ("voltage_v", {"volt", "volts", "voltage"}, None)],
    "air_quality": [("aqi", {"aqi", "index"}, None), ("pm25_ugm3", {"pm25", "pm2"}, None), ("pm10_ugm3", {"pm10"}, None)],
}
REQUIRED = {"water_level": ["level_m"], "traffic_camera": ["congestion_score", "vehicle_count", "avg_speed_kmh"],
            "power_load": ["load_kw", "capacity_kw", "voltage_v"], "air_quality": ["aqi", "pm25_ugm3", "pm10_ugm3"]}

# A suffix on their field name says its unit: scale to ours. (unit of ours) -> {suffix: scale}
UNITS = {"length": {"cm": 0.01, "mm": 0.001, "ft": 0.3048, "in": 0.0254, "m": 1.0}, "fraction": {"pct": 0.01, "percent": 0.01},
         "kw": {"w": 0.001, "mw": 1000.0, "kw": 1.0}}


def words(name: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", name).lower()) if w]


def _similar(word: str, vocabulary: set[str]) -> float:
    if word in vocabulary:
        return 1.0
    best = max((SequenceMatcher(None, word, v).ratio() for v in vocabulary), default=0.0)
    return best if best >= 0.8 else 0.0


@dataclass
class Proposal:
    type_aliases: dict[str, str] = field(default_factory=dict)
    profiles: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    lines: list[dict[str, Any]] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)

    def yaml(self) -> str:
        out = ["twin:"]
        out.append("  type_aliases: {" + ", ".join(f"{a}: {b}" for a, b in self.type_aliases.items()) + "}")
        out.append("  profiles:")
        for kind, fields in self.profiles.items():
            body = ", ".join(f"{name}: {{from: {p['from']}" + (f", scale: {p['scale']:g}" if p["scale"] != 1 else "") + (f", offset: {p['offset']:g}" if p["offset"] else "") + "}" for name, p in fields.items())
            out.append(f"    {kind}: {{{body}}}")
        for l in self.lines:
            if l["review"]:
                out.append(f"  # REVIEW: {l['theirs']} -> {l['ours']} is only {l['confidence']:.2f} sure ({l['evidence']})")
        for t in self.unmapped:
            out.append(f"  # UNMAPPED: {t} fits no contract type; add a pack (INTERFACE.md, When the Twin changes) or ignore it")
        return "\n".join(out)


def _match_fields(kind: str, theirs: dict[str, list[Any]]) -> tuple[dict[str, dict[str, Any]], float]:
    """For each required field of `kind`, the field of theirs that best fits it, with the scale that converts it."""
    chosen: dict[str, dict[str, Any]] = {}
    for ours, vocabulary, unit in FIELDS[kind]:
        best, score = None, 0.0
        for name, values in theirs.items():
            if not any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
                continue
            parts = words(name)
            match = max((_similar(w, vocabulary | set(words(ours))) for w in parts), default=0.0)
            if match > score:
                best, score = name, match
        if best is not None and score >= 0.8:
            scale = 1.0
            if unit in UNITS:
                for part in words(best):
                    if part in UNITS[unit]:
                        scale = UNITS[unit][part]
            chosen[ours] = {"from": best, "scale": scale, "offset": 0.0}
    required = REQUIRED[kind]
    return chosen, sum(1 for r in required if r in chosen) / len(required)


def propose(readings: list[dict[str, Any]]) -> Proposal:
    by_type: dict[str, dict[str, list[Any]]] = {}
    for reading in readings:
        fields = by_type.setdefault(str(reading.get("type")), {})
        for key, value in (reading.get("value") or {}).items():
            fields.setdefault(key, []).append(value)
    proposal = Proposal()
    for theirs, fields in sorted(by_type.items()):
        if theirs in TYPE_WORDS:  # already one of ours
            continue
        candidates = []
        for kind, vocabulary in TYPE_WORDS.items():
            name_score = max((_similar(w, vocabulary) for w in words(theirs)), default=0.0)
            chosen, coverage = _match_fields(kind, fields)
            candidates.append((0.5 * name_score + 0.5 * coverage, kind, chosen, name_score, coverage))
        confidence, kind, chosen, name_score, coverage = max(candidates, key=lambda c: c[0])
        if confidence < ACCEPT:
            proposal.unmapped.append(theirs)
            continue
        proposal.type_aliases[theirs] = kind
        renamed = {f: p for f, p in chosen.items() if p["from"] != f or p["scale"] != 1.0}
        if renamed:
            proposal.profiles.setdefault(kind, {}).update(renamed)
        proposal.lines.append({"kind": "type", "theirs": theirs, "ours": kind, "confidence": round(confidence, 2), "review": confidence < FLOOR,
                               "evidence": f"name {name_score:.2f}, fields {coverage:.2f}; " + ", ".join(f"{p['from']} -> {f}" + (f" x{p['scale']:g}" if p["scale"] != 1 else "") for f, p in chosen.items())})
        for ours, p in chosen.items():
            proposal.lines.append({"kind": "field", "theirs": f"{theirs}.{p['from']}", "ours": f"{kind}.{ours}", "confidence": round(confidence, 2), "review": confidence < FLOOR,
                                   "evidence": f"scale {p['scale']:g}"})
    return proposal
