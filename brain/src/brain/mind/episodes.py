"""Episodes: what the Brain keeps of each closed incident, so that quiet time can learn from it.

An episode holds the readings the Brain saw around the incident (typed values only, people renamed
`p-1`, `p-2`... inside the episode), the Guardian's verdict on each, and what each tier decided. It holds
no identity, no unit id and no `target_id`, and it never records whether a dispatch worked: the only
thing sleep may learn from is a plan the deliberator made and the verifier passed.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from brain.citygraph import MemoryGraphStore
from brain.contracts import SensorReading, TimelineEvent

DROPPED_PARAMS = {"incident_id", "target_id", "unit_id"}
PERSON_FIELDS = ("citizen_id", "entity_id")


class EpisodeReading(BaseModel):
    reading_id: str
    sensor_id: str
    type: str
    zone_id: str
    at_ms: int
    value: dict[str, Any]
    verdict: str
    verdict_id: str


class PlanAction(BaseModel):
    action: str
    params: dict[str, Any]


class PlanRecord(BaseModel):
    reason: str
    actions: list[PlanAction]


class IncidentRef(BaseModel):
    type: str
    zone_id: str


class Pursuit(BaseModel):
    zone_id: str  # where the suspect was last seen when the pursuit went out
    heading_zone_id: str | None = None  # and where that sighting said they were heading


class Episode(BaseModel):
    episode_id: str
    incident: IncidentRef
    readings: list[EpisodeReading]
    pursuits: list[Pursuit] = Field(default_factory=list)
    plans: list[PlanRecord] = Field(default_factory=list)
    lessons_used: list[str] = Field(default_factory=list)  # learned rules that answered this incident in place of a team run
    team_runs: int = 0
    outcome: str = ""
    config_hash: str = ""
    scenario_id: str | None = None
    topology: str | None = None  # the hash of the city layout it happened in (see EpisodeStore.save_topology)


class EpisodeStore:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.path = folder / "episodes.jsonl"

    def append(self, episode: Episode) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(episode.model_dump(mode="json"), sort_keys=True) + "\n")

    def all(self) -> tuple[list[Episode], int]:
        """Every readable episode, and how many lines could not be read (a crash mid-write, a hand edit)."""
        episodes, bad = [], 0
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    episodes.append(Episode.model_validate(json.loads(line)))
                except (json.JSONDecodeError, ValidationError):
                    bad += 1
        return episodes, bad

    def save_topology(self, topology: dict[str, Any]) -> str:
        digest = hashlib.sha256(json.dumps(topology, sort_keys=True).encode()).hexdigest()[:8]
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"topology-{digest}.json").write_text(json.dumps(topology, indent=2, sort_keys=True) + "\n")
        return digest

    def topology(self, digest: str) -> dict[str, Any]:
        return json.loads((self.folder / f"topology-{digest}.json").read_text())


class _Open:
    def __init__(self) -> None:
        self.decisions: list[dict[str, Any]] = []
        self.reason: str | None = None
        self.plans: dict[str, list[dict[str, Any]]] = {}
        self.pursuits: list[Pursuit] = []
        self.lessons: list[str] = []
        self.team_runs = 0


class EpisodeRecorder:
    """A timeline sink: it watches the Brain's own events and writes an episode when an incident closes."""

    def __init__(self, store: MemoryGraphStore, episodes: EpisodeStore, lookback_s: float = 120.0, buffer: int = 4000) -> None:
        self.store = store
        self.episodes = episodes
        self.lookback_s = lookback_s
        self.topology: str | None = None
        self.config_hash = ""
        self.scenario_id: str | None = None
        self._readings: deque[SensorReading] = deque(maxlen=buffer)
        self._open: dict[str, _Open] = {}

    def set_topology(self, topology: dict[str, Any]) -> None:
        self.topology = self.episodes.save_topology(topology)

    def note_reading(self, reading: SensorReading) -> None:
        """Called by the runtime once a reading is in the store, with its verdict."""
        self._readings.append(reading)

    def write(self, event: TimelineEvent) -> None:
        kind, data, subject = event.type, event.data, event.subject or ""
        if kind == "brain.scenario.started":
            self.scenario_id = subject
        elif kind == "brain.started":
            self.config_hash = data.get("config_hash", "")
        elif kind == "brain.incident.opened":
            self._open[subject] = _Open()
        elif kind == "brain.deliberation.started" and subject in self._open:
            self._open[subject].reason = data.get("reason")
            self._open[subject].team_runs += 1
        elif kind == "brain.deliberation.finished" and subject in self._open:
            self._open[subject].reason = None
        elif kind == "brain.decision.made" and subject in self._open:
            opened = self._open[subject]
            opened.decisions.append(data)
            if data.get("tier") == "reflex" and data["action"] == "dispatch_unit" and data["params"].get("mode") == "pursuit":
                last = (self.store.sightings(data["params"].get("target_id", "")) or [None])[-1]
                opened.pursuits.append(Pursuit(zone_id=data["params"]["zone_id"], heading_zone_id=last.heading_zone_id if last else None))
            if data.get("tier") == "deliberate" and opened.reason:
                params = {k: v for k, v in data["params"].items() if k not in DROPPED_PARAMS}
                opened.plans.setdefault(opened.reason, []).append({"action": data["action"], "params": params})
        elif kind == "brain.plan.compiled" and subject in self._open:
            self._open[subject].lessons.append(data.get("rule_id", ""))
        elif kind == "brain.incident.closed" and subject in self._open:
            self._finish(subject, data.get("outcome", ""))

    def _finish(self, incident_id: str, outcome: str) -> None:
        opened, incident = self._open.pop(incident_id), self.store.incident(incident_id)
        if incident is None:
            return
        since = incident.occurred_at.timestamp() - self.lookback_s
        seen = [r for r in self._readings if r.timestamp.timestamp() >= since and r.type != "unit_status"]
        if not seen:
            return
        origin, aliases = seen[0].timestamp, {}

        def alias(value: dict[str, Any]) -> dict[str, Any]:
            clean = dict(value)
            for name in PERSON_FIELDS:
                if isinstance(clean.get(name), str):
                    clean[name] = aliases.setdefault(clean[name], f"p-{len(aliases) + 1}")
            return clean

        readings = []
        for reading in seen:
            verdict = self.store.verdict_of(reading.reading_id)
            readings.append(EpisodeReading(
                reading_id=reading.reading_id, sensor_id=reading.sensor_id, type=reading.type, zone_id=reading.zone_id,
                at_ms=int((reading.timestamp - origin).total_seconds() * 1000), value=alias(reading.value),
                verdict=verdict.status.value if verdict else "unknown", verdict_id=verdict.verdict_id if verdict else "",
            ))
        # The time is in the hash so that the same pattern happening twice is two episodes, not one counted twice.
        digest = hashlib.sha256((json.dumps([r.model_dump() for r in readings], sort_keys=True) + str(time.time_ns())).encode()).hexdigest()[:8]
        self.episodes.append(Episode(
            episode_id=f"ep-{incident_id}-{digest}", incident=IncidentRef(type=incident.type, zone_id=incident.zone_id),
            readings=readings,
            pursuits=opened.pursuits, lessons_used=sorted(set(opened.lessons)),
            plans=[PlanRecord(reason=reason, actions=[PlanAction(**a) for a in actions]) for reason, actions in opened.plans.items()],
            team_runs=opened.team_runs, outcome=outcome, config_hash=self.config_hash, scenario_id=self.scenario_id,
            topology=self.topology,
        ))
