"""BrainService: the loop that turns a stream of readings into decisions.

    reading -> perception -> Guardian verdict -> City Graph -> triage -> reflex graph
                                                                             |
                                                           department team (background)

Given a state file, the service saves what it knows after every reading and picks it up
again on the next start (see `brain.persistence`).
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brain import clock, config
from brain.approval import ApprovalStore
from brain.citygraph import MemoryGraphStore
from brain.config import ModelsConfig, PartnersConfig, Policy, fingerprint, secret
from brain.contracts import (
    AirQuality,
    CctvAnomaly,
    CitizenActivity,
    EmergencyCall,
    Gunshot,
    Incident,
    PowerLoad,
    ReadingRef,
    SensorReading,
    TrafficCamera,
    TrustVerdict,
    UnitStatus,
    VerdictStatus,
    WaterLevel,
    utcnow,
)
from brain.contracts.keyring import KeyRing
from brain.contracts.models import SAFE_ID
from brain.departments import discover_manifests, load_learned_rules, load_rules
from brain.departments.builder import Deliberations, TeamDeps, _cassette, build_department, make_crews
from brain.departments.police import assess
from brain.departments.team import LLMCrew
from brain.gate import ActuationGate
from brain.graph import Deps, build_incident_graph
from brain.graph.actuation import Actuation, execute_approvals, gate_proposals, stand_down
from brain.journal import JournalWriter, reading_record
from brain.knowledge import (
    KnowledgeBase,
    capabilities_as_knowledge,
    load_playbook,
    playbook_exists,
    rules_as_knowledge,
)
from brain.knowledge.corpus import reference_items
from brain.knowledge.embedding import make_embedder
from brain.knowledge.graph import check_links
from brain.knowledge.memory import MemoryKnowledgeBase
from brain.llm_health import LLMHealth
from brain.mind.bids import bid
from brain.mind.bus import Bus, IncidentClosed, IncidentTouched, Percept
from brain.mind.effects import ActionEffects
from brain.mind.episodes import EpisodeRecorder, EpisodeStore
from brain.mind.forward import ForwardModels
from brain.mind.neighbours import NeighbourModels
from brain.mind.surface import apply_overlay, load_overlay
from brain.mind.workspace import Workspace
from brain.perception import ContractError, Perception
from brain.persistence import StateFile
from brain.ports import GuardianPort, GuardianUnavailable, TwinError, TwinPort
from brain.timeline import Timeline
from brain.triage import Triage


def _summary(value: Any) -> str:
    """A few words on what a reading says, for the timeline. Built from typed fields only."""
    if isinstance(value, CitizenActivity):
        return f"{value.activity}, {value.speed_kmh:.0f} km/h"
    if isinstance(value, CctvAnomaly):
        return f"{value.anomaly_type} ({value.confidence:.2f})"
    if isinstance(value, Gunshot):
        return f"gunshot {'detected' if value.detected else 'not detected'} ({value.confidence:.2f})"
    if isinstance(value, EmergencyCall):
        return f"{value.category} call"
    if isinstance(value, UnitStatus):
        return f"{value.unit_id} {value.state.replace('_', ' ')}"
    if isinstance(value, TrafficCamera):
        return f"congestion {value.congestion_score:.2f}, {value.avg_speed_kmh:.0f} km/h" + (", smoke" if value.smoke_detected else "")
    if isinstance(value, WaterLevel):
        return f"level {value.level_m:.2f} m"
    if isinstance(value, PowerLoad):
        return f"load {value.load_kw:.0f} of {value.capacity_kw:.0f} kW"
    if isinstance(value, AirQuality):
        return f"AQI {value.aqi}"
    return ""


class BrainService:
    def __init__(
        self,
        partners: PartnersConfig,
        policy: Policy,
        twin: TwinPort,
        guardian: GuardianPort,
        timeline: Timeline,
        models: ModelsConfig | None = None,
        *,
        store: MemoryGraphStore | None = None,
        kb: KnowledgeBase | None = None,
        llm_crew: LLMCrew | None = None,
        llm_health: LLMHealth | None = None,
        state: StateFile | None = None,
        journal: JournalWriter | None = None,
    ) -> None:
        self.journal = journal
        self.partners = partners
        # What the Academy tuned, if anything: an overlay over the policy, limited to the tunable surface.
        self.tuned, self.tuned_problem = load_overlay(partners.brain.tuned_dir)
        policy = apply_overlay(policy, self.tuned)
        self.policy = policy
        self.twin = twin
        self.guardian = guardian
        self.timeline = timeline
        # With `approval.mode: human` a held high-impact call waits here for a person (see brain.approval); otherwise the gate just holds it.
        self.approvals = None
        if partners.approval.mode == "human":
            self.approvals = ApprovalStore(partners.approval.path, secret(partners.approval.secret_env) or "", partners.approval.ttl_s)
            self.approvals.emit = timeline.emit
        self.models = models or ModelsConfig()
        self.store = store or MemoryGraphStore()
        self.kb = kb
        self._twin_down = False
        self.keyring = KeyRing.from_config(partners.security.keys) if partners.security.keys else None
        self.perception = Perception(
            partners.brain.accepted_contract_versions,
            secret(partners.twin.hmac_secret_env),
            partners.twin.require_signature,
            partners.twin.profiles,
            partners.twin.type_aliases,
            self.keyring,
            partners.twin.max_age_s,
            partners.twin.dialect,
        )
        packs_dir = partners.brain.packs_dir
        self._packs_dir = (Path(packs_dir) if Path(packs_dir).is_absolute() else config.home() / packs_dir) if packs_dir else None
        self.packs, self._pack_problems = discover_manifests(self._packs_dir)
        self.triage = Triage(policy, self.store, self.packs)
        self.bus = Bus()
        self.workspace: Workspace | None = None
        self.forward: ForwardModels | None = None
        self._trackers: dict[str, Any] = {}  # one level tracker per water sensor (`math.kalman: on`)
        self._last_estimate: dict[str, float] = {}
        self.forecasts: dict[str, dict[str, Any]] = {}  # the latest crossing forecast per water sensor, for the teams' briefs and the early alert
        self._warned: set[str] = set()  # sensors already warned about; the level falling back, or moving away from the line, rearms them
        self.neighbours: NeighbourModels | None = None
        if policy.forward.enabled:
            self.forward = ForwardModels(policy.forward)
            if policy.forward.coupled:
                self.neighbours = NeighbourModels(policy.forward, self.forward)
            self.bus.subscribe(Percept, self._on_percept)
            if policy.forward.effects:
                timeline.sinks.append(ActionEffects(policy.forward.effects, self.store, self.forward))
        if policy.workspace.enabled:
            # A pack rates its own incident types; the policy's table covers whatever no pack rates.
            severity = {**policy.workspace.severity, **{k: v for pack in self.packs.values() for k, v in pack.severity.items()}}
            workspace_policy = policy.workspace.model_copy(update={"severity": severity})
            self.workspace = Workspace(workspace_policy, self.store, self.triage.incidents, timeline, self._surprise_of, self._bids if policy.workspace.bids else None, self._urgency_of)
            self.bus.subscribe(IncidentClosed, self.workspace.on_closed)
            self.bus.subscribe(IncidentTouched, self.workspace.on_touched)
        self.recorder: EpisodeRecorder | None = None
        if partners.brain.episodes_dir:
            folder = Path(partners.brain.episodes_dir)
            self.recorder = EpisodeRecorder(self.store, EpisodeStore(folder if folder.is_absolute() else config.home() / folder))
            timeline.sinks.append(self.recorder)
        self.deliberations: Deliberations | None = None
        self.desks: Deliberations | None = None  # the agent desks of the other departments (`team.departments: on`)
        self._actuation: Actuation | None = None
        self._llm_crew = llm_crew
        # Shared by every model crew of this Brain; a server passes one that outlives a scenario, so a person's choice of the scripted team stays.
        self.llm_health = llm_health if llm_health is not None else LLMHealth(emit=timeline.emit)
        self._state = state
        self._handling = False
        self._topology_hash = ""
        self._guardian_up = True
        self._capabilities: set[str] = set()
        self._reported_capabilities: set[str] | None = None
        self._capabilities_checked = datetime.min.replace(tzinfo=UTC)
        self._graph: Any = None

    async def start(self) -> None:
        topology = await self.twin.get_topology()
        self.store.load_topology(topology)
        self._topology_hash = fingerprint(topology)
        capabilities = await self.twin.list_capabilities()
        self._capabilities = self._reported_capabilities = set(capabilities)
        if self.recorder is not None:
            self.recorder.set_topology(topology)

        # Police has the agent team; the other packs are reflex-only (flood, jam, fire...).
        manifests = self.packs
        manifest = manifests["POLICE"]
        rules = [rule for m in manifests.values() if m.reflex_rules for rule in load_rules(m.reflex_rules, m.code, self._packs_dir)]
        learned = self.policy.learning.use_learned and self.partners.brain.learned_dir
        if learned:
            folder = Path(learned)
            rules += load_learned_rules(folder if folder.is_absolute() else config.home() / folder, "POLICE")
        config_hash = fingerprint(self.policy, [m.model_dump(mode="json") for m in manifests.values()], [rule.model_dump(mode="json") for rule in rules])
        gate = ActuationGate(
            self.store, self.twin, self.guardian, self.policy.gate, manifests,
            set(capabilities), secret(self.partners.brain.signing_secret_env), approvals=self.approvals, keyring=self.keyring,
        )
        actuation = self._actuation = Actuation(self.store, gate, self.timeline, manifest, config_hash, rules=rules,
                                                manifests=manifests)
        if self.policy.orchestration.planner == "on":
            from brain.plan.corridor import CorridorPlanner

            settings = self.policy.orchestration
            actuation.on_dispatch = CorridorPlanner(actuation, set(capabilities), settings.corridor_units, settings.checkpoint_db, settings.max_checkpoints).on_dispatch
        if self.policy.optimiser.shed == "on":
            from brain.engines.shed import FeederShedder

            actuation.shedder = FeederShedder(self.policy.optimiser.shed_target_ratio, self.policy.optimiser.time_limit_ms)
        if self.policy.optimiser.dispatch == "on":
            from brain.engines.dispatch import OptimalChooser

            severity = {**self.policy.workspace.severity, **{t: v for m in manifests.values() for t, v in m.severity.items()}}
            actuation.chooser = OptimalChooser(severity, self.policy.optimiser.time_limit_ms, self.policy.optimiser.unmet_penalty)

        embedder_note = ""
        if self.kb is None:
            embedder, embedder_note = make_embedder(self.models.embeddings.provider, self.models.embeddings.model)
            self.kb = MemoryKnowledgeBase(embedder, self.models.knowledge)
        knowledge = [
            *(item for m in manifests.values() if playbook_exists(m.code) for item in load_playbook(m.code)),
            *(item for m in manifests.values() for item in rules_as_knowledge(m.code, [r for r in rules if r.department == m.code])),
            *capabilities_as_knowledge(capabilities),
            *reference_items(self.partners.brain.reference_docs, config.home()),
        ]
        knowledge, link_problems = check_links(knowledge)  # an item with a bad link stays; only the link goes
        if link_problems:
            self._pack_problems.append(("playbooks", "a knowledge link was dropped, the item stays: " + "; ".join(link_problems)))
        if getattr(self.kb, "emit", False) is None:  # a resilient knowledge base says when it falls back and when it is back
            self.kb.emit = self.timeline.emit
        await self.kb.sync(knowledge)

        team = self.models.team
        crew = "off"
        if team.enabled:
            scripted, llm = make_crews(manifest, self.policy, self.models)
            llm = self._llm_crew or llm
            if llm is not None:
                llm.health = self.llm_health
            crew = "llm" if llm is not None else "scripted"
            deps = TeamDeps(
                actuation=actuation, policy=self.policy, kb=self.kb, incidents=self.triage.incidents,
                capabilities=set(capabilities), scripted=scripted, llm=llm, max_revisions=team.max_revisions,
                stories=self._stories if self.partners.brain.episodes_dir else None, embedder=self.kb.embedder,
                relative_times=team.relative_times, forecasts=lambda: self.forecasts,
            )
            self.deliberations = Deliberations(
                build_department(manifest, deps), deps, self.timeline, team.budget_s, self._team_started_pursuit,
                self._team_finished,
            )
            if team.departments == "on":  # the other departments' desks: an analyst and a chief each, advising neighbouring zones
                from brain.departments.desk import DeskGraph, make_desk_crews

                crews = make_desk_crews(manifests, self.models.roles, {k: self.models.options_for(k) for k in self.models.roles}, team.structured_output,
                                        team.llm and team.cassette != "replay", _cassette(self.models))
                for desk_crew in crews.llm.values():
                    desk_crew.health = self.llm_health
                desk_deps = TeamDeps(
                    actuation=actuation, policy=self.policy, kb=self.kb, incidents=self.triage.incidents, capabilities=set(capabilities),
                    scripted=scripted, llm=None, embedder=self.kb.embedder, relative_times=team.relative_times, forecasts=lambda: self.forecasts)
                self.desks = Deliberations(DeskGraph(desk_deps, crews, manifests), desk_deps, self.timeline, team.budget_s, None, self._team_finished)

        self._graph = build_incident_graph(Deps(
            actuation=actuation, policy=self.policy, rules=rules, incidents=self.triage.incidents,
            request_deliberation=self._deliberation_request(),
            doubted=self.forward.is_doubted if self.forward else None,
        ))
        self.timeline.emit("brain.started", None, {
            "capabilities": sorted(capabilities),
            "topology": self.store.topology(),
            "departments": list(manifests),
            "team": {"crew": crew, "budget_s": team.budget_s},
            "workspace": {"enabled": self.workspace is not None, "slots": self.policy.workspace.slots},
            "forward": {"enabled": self.forward is not None},
            "knowledge": {"items": len(knowledge), "backend": type(self.kb).__name__, "note": embedder_note},
            "graph_backend": type(self.store).__name__,
            "guardian_mode": self.partners.guardian.mode,
            "verify_twin_signatures": self.perception.twin_secret is not None,
            "config_hash": config_hash,
            "tuned": self.tuned, "tuned_problem": self.tuned_problem,
            "state_file": str(self._state.path) if self._state else None,
        })
        for file_name, reason in self._pack_problems:
            self.timeline.emit("brain.pack.rejected", file_name, {"file": file_name, "reason": reason})
        if self._state is not None:
            await self._restore()
            self.store.journal = self._state.record

    def _stories(self) -> list:
        """The episodes kept so far, for the Analyst's `episodes.similar` tool."""
        folder = Path(self.partners.brain.episodes_dir)
        return EpisodeStore(folder if folder.is_absolute() else config.home() / folder).all()[0]

    def _bids(self, incident: Incident) -> list:
        return [bid(pack, incident, self._capabilities, self.store) for pack in self.packs.values()]

    def _surprise_of(self, incident: Incident) -> float:
        """0 to 1: how far the newest evidence sat from what the forward models predicted."""
        if self.forward is None:
            return 0.0
        return min(self.forward.strongest_z(incident.evidence) / (2 * self.policy.forward.z_threshold), 1.0)

    def _urgency_of(self, incident: Incident) -> float:
        """0 to 1: for a flood, how fast the water is still rising, from the level forecast (full at `urgency_full_rate_m_per_min`)."""
        full = self.policy.workspace.urgency_full_rate_m_per_min
        if incident.type != "flood" or full <= 0:
            return 0.0
        rates = [f["rate_m_per_min"] for f in self.forecasts.values() if f["zone_id"] == incident.zone_id]
        return min(max(max(rates, default=0.0), 0.0) / full, 1.0)

    def retract(self, reading_id: str, reason: str) -> dict[str, Any] | None:
        """The Guardian (or an operator) takes back its verdict on a reading. Returns None if the Brain never saw it.

        Every later action that cites the reading is refused at the gate (`trust_ref`); actions already sent are not
        recalled. Any forward-model baseline that learned from the reading is rebuilt without it. The retraction is kept
        in the learned folder so that sleep revokes what the reading taught.
        """
        revised = self.store.retract_verdict(reading_id, reason)
        if revised is None:
            return None
        incidents = sorted(i.incident_id for i in self.triage.incidents.values() if reading_id in i.evidence)
        rebuilt = self.forward.forget(reading_id) if self.forward is not None else []
        withdrawn = self.store.reading(reading_id)
        if withdrawn is not None and withdrawn.sensor_id in self._trackers:
            self._trackers[withdrawn.sensor_id].retract(withdrawn.timestamp.timestamp())
        episodes, rules = self._taught_by(reading_id)
        self.timeline.emit("brain.evidence.retracted", reading_id, {
            "reading_id": reading_id, "reason": reason, "verdict_id": revised.verdict_id, "incidents": incidents,
            "baselines_rebuilt": [f"{sensor}.{field}" for sensor, field in rebuilt],
            # The rest of what rests on the reading: stored episodes that contain it, and learned rules those taught.
            # Sleep revokes the rules; this says so before it does.
            "episodes": episodes, "rules": rules,
        })
        if self.partners.brain.learned_dir:
            folder = Path(self.partners.brain.learned_dir)
            folder = folder if folder.is_absolute() else config.home() / folder
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / "retractions.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps({"reading_id": reading_id, "reason": reason, "at": utcnow().isoformat()}) + "\n")
        return {"reading_id": reading_id, "incidents": incidents}

    def _taught_by(self, reading_id: str) -> tuple[list[str], list[str]]:
        """(stored episodes containing this reading, learned rules those episodes taught)."""
        brain = self.partners.brain
        if not brain.episodes_dir:
            return [], []
        folder = Path(brain.episodes_dir)
        episodes, _ = EpisodeStore(folder if folder.is_absolute() else config.home() / folder).all()
        hit = sorted(e.episode_id for e in episodes if any(r.reading_id == reading_id for r in e.readings))
        rules: list[str] = []
        if hit and brain.learned_dir:
            learned = Path(brain.learned_dir)
            path = (learned if learned.is_absolute() else config.home() / learned) / "rules.yaml"
            if path.is_file():
                import yaml

                rules = sorted(r["id"] for r in (yaml.safe_load(path.read_text()) or {}).get("rules", [])
                               if set((r.get("learned") or {}).get("sources", [])) & set(hit))
        return hit, rules

    def _estimate(self, percept: Percept, trusted: bool) -> None:
        """With `math.kalman: on`, track each water level and say, when the estimate moves by a tenth, when it will cross the line."""
        settings = self.policy.math
        if settings.kalman != "on" or percept.reading.type != "water_level":
            return
        from brain.engines.kalman import LevelTracker

        sensor = percept.reading.sensor_id
        tracker = self._trackers.setdefault(sensor, LevelTracker(measurement_var=settings.kalman_measurement_var))
        tracker.update(percept.reading.timestamp.timestamp(), float(percept.value.level_m), trusted)
        arrival = tracker.time_to(settings.kalman_threshold_m)
        if not trusted:
            return
        level, rate, _ = tracker.state()
        coming = 0 < arrival.mean_s <= settings.kalman_horizon_s
        # kept after the line is crossed too (without a time): the Disaster desk reads the trend of a flood that has begun
        self.forecasts[sensor] = {"sensor_id": sensor, "zone_id": percept.reading.zone_id, "level_m": round(level, 3), "rate_m_per_min": round(rate * 60, 3),
                                  "threshold_m": settings.kalman_threshold_m, "seconds_to_threshold": round(arrival.mean_s) if coming else None,
                                  "interval_s": round(arrival.sd_s) if coming else None, "within_10_min": round(arrival.p_within(600.0), 2) if coming else 0.0}
        if not coming:
            self._warned.discard(sensor)
            return
        previous = self._last_estimate.get(sensor)
        if previous is not None and abs(arrival.mean_s - previous) < 0.1 * previous:
            return
        self._last_estimate[sensor] = arrival.mean_s
        known = self.forecasts[sensor]
        self.timeline.emit("brain.math.estimated", sensor, {k: known[k] for k in ("sensor_id", "level_m", "rate_m_per_min", "threshold_m", "seconds_to_threshold", "interval_s", "within_10_min")},
                           percept.trace_id)

    async def _prewarn(self, reading: SensorReading, trace_id: str) -> None:
        """A flood forecast close enough to the line sends one low-impact alert before the line is crossed, through the gate like any alert.

        It belongs to no incident (none is open yet): the proposal names a watch on the sensor, and the real flood incident, if the line is crossed, gets its own alert."""
        known, settings = self.forecasts.get(reading.sensor_id), self.policy.math
        if known is None or known["seconds_to_threshold"] is None or settings.prewarn_s <= 0 or reading.sensor_id in self._warned or known["seconds_to_threshold"] > settings.prewarn_s:
            return
        if self.forward is not None and self.forward.is_doubted(reading.reading_id):
            return  # a level the forward models doubt, or a coupled sensor disputes, is no ground for a public alert: it waits like the reflex does
        if self.neighbours is not None:  # sensors the Twin says move together must forecast the crossing too, or the partner would dispute this one
            partners = {s for group in self.neighbours.groups if reading.sensor_id in group for s in group} - {reading.sensor_id}
            if any((self.forecasts.get(s) or {}).get("seconds_to_threshold") is None for s in partners):
                return
        if any(i.type == "flood" and i.zone_id == reading.zone_id and i.status == "open" for i in self.triage.incidents.values()):
            return  # the line is already crossed: the incident's own alert is the warning
        act = self._actuation
        manifest = act.manifests.get("DISASTER") if act is not None else None
        if manifest is None or "broadcast_alert" not in manifest.actuators:
            return
        from brain.contracts import Incident
        from brain.graph.actuation import execute_approvals, gate_proposals, make_proposal

        self._warned.add(reading.sensor_id)
        zone = str(self.store.zones.nodes[reading.zone_id].get("name", reading.zone_id)) if reading.zone_id in self.store.zones else reading.zone_id
        minutes = max(1, round(known["seconds_to_threshold"] / 60))
        watch = Incident(incident_id=f"watch-{reading.sensor_id}", type="flood", zone_id=reading.zone_id, occurred_at=reading.timestamp,
                         evidence=[reading.reading_id], departments=["DISASTER"])
        proposal = make_proposal(
            act, watch, [reading.reading_id], "broadcast_alert",
            {"message": self.policy.desks.prewarning.format(zone=zone, when=f"{minutes} minute{'' if minutes == 1 else 's'}"), "channel": self.policy.tactics.alert_channel, "zone_id": reading.zone_id},
            tier="reflex", justification=f"{reading.sensor_id} is at {known['level_m']} m and rising {known['rate_m_per_min']} m/min: about {known['seconds_to_threshold']} s to the {known['threshold_m']} m line.",
            manifest=manifest)
        if proposal is None:
            return
        self.timeline.emit("brain.forecast.warned", reading.sensor_id, {**{k: known[k] for k in ("sensor_id", "zone_id", "level_m", "rate_m_per_min", "threshold_m", "seconds_to_threshold")}, "minutes": minutes}, trace_id)
        self.store.add_incident(watch)  # the decision links to it; it is closed again at once, so nothing else treats it as an open incident
        try:
            approvals, _ = await gate_proposals(act, [proposal.model_dump(mode="json")], [], trace_id)
            if approvals:
                await execute_approvals(act, approvals, trace_id)
        finally:
            watch.status, watch.outcome = "closed", "forecast alert sent"
            self.store.close_incident(watch)

    def _on_percept(self, percept: Percept) -> None:
        """The forward models predict each environmental sensor from its history and report what does not fit."""
        if percept.value is None:
            return
        trusted = percept.verdict.status == VerdictStatus.TRUSTED
        self._estimate(percept, trusted)
        found = self.forward.observe(percept.reading, percept.value, trusted)
        if self.neighbours is not None:
            found = [*found, *self.neighbours.observe(percept.reading, percept.value, trusted)]
        for surprise in found:
            self.timeline.emit("brain.percept.surprise", percept.reading.reading_id, {
                "sensor_id": surprise.sensor_id, "field": surprise.field, "observed": surprise.observed,
                "expected": surprise.expected, "spread": surprise.spread, "z": surprise.z, "run": surprise.run,
                "doubted": surprise.doubted, "rebaselined": surprise.rebaselined, "verdict": percept.verdict.status.value,
                "threshold": surprise.threshold, "recovered": surprise.recovered, "explained": surprise.explained,
                "kind": surprise.kind, "neighbour": surprise.neighbour,
            }, percept.trace_id)

    def _deliberation_request(self) -> Any:
        """The reflex graph asks the team through here: only an incident that holds a workspace slot gets a model."""
        if self.deliberations is None:
            return None
        request = self.deliberations.request
        if self.workspace is None:
            return request

        def gated(incident_id: str, *rest: Any) -> None:
            if self.workspace.is_lit(incident_id):
                request(incident_id, *rest)
            else:
                self.workspace.counts["suppressed"] += 1

        return gated

    # ------------------------------------------------------------------ state across restarts

    async def _restore(self) -> None:
        """Pick up the state saved by an earlier run of this Brain, if it is still the same session."""
        saved = self._state.load()
        if saved is None:
            return
        snapshot, journal = saved
        meta = snapshot["meta"]
        age_s = (utcnow() - datetime.fromisoformat(meta["saved_at"])).total_seconds()
        reason = None
        if meta.get("topology") != self._topology_hash:
            reason = "the Twin's city layout is not the one the state was saved for"
        elif age_s > self.partners.brain.state_max_age_s:
            reason = f"it was saved {age_s:.0f} s ago, more than state_max_age_s ({self.partners.brain.state_max_age_s:.0f} s)"
        elif meta.get("position") and hasattr(self.twin, "resume") and not await self.twin.resume(meta["position"]):
            reason = "the Twin has started a new stream since"
        if reason is not None:
            self._state.clear()
            self.timeline.emit("brain.state.discarded", None, {"reason": reason, "saved_at": meta["saved_at"]})
            return

        for kind, payload in journal:
            self.store.replay(kind, payload)
        self.store.restore(snapshot.get("store", {}))
        self.triage.restore(snapshot.get("triage", {}))
        self.perception.restore(snapshot.get("perception", {}))
        act = self._actuation
        act.gate.restore(snapshot.get("gate", {}))
        act.decisions = int(snapshot.get("actuation", {}).get("decisions", 0))
        act.plans = {(p["incident_id"], p["entity_id"]): p["plan"] for p in snapshot.get("actuation", {}).get("plans", [])}
        for incident_id, values in snapshot.get("reflex", {}).items():
            await self._graph.aupdate_state({"configurable": {"thread_id": incident_id}}, values, as_node="actuate")
        if self.deliberations is not None:
            self.deliberations.restore(snapshot.get("deliberations", {}))

        incidents = list(self.triage.incidents.values())
        self.timeline.emit("brain.state.restored", None, {
            "saved_at": meta["saved_at"], "age_s": round(age_s, 1),
            "incidents_open": [i.incident_id for i in incidents if i.status == "open"],
            "incidents_closed": len([i for i in incidents if i.status == "closed"]),
            "readings": sum(1 for kind, _ in journal if kind == "reading"),
            "decisions": act.decisions,
            "units_out": [unit["unit_id"] for unit in self.store.units_out()],
        })
        # A plan the team was still working on when the Brain stopped was lost with it: ask again.
        if self.deliberations is not None:
            for incident in incidents:
                pursued = snapshot.get("reflex", {}).get(incident.incident_id, {}).get("pursued", {})
                for entity_id in pursued if incident.status == "open" else []:
                    if not self.deliberations.finished(incident.incident_id, entity_id, "plan"):
                        assessment = assess(incident, entity_id, self.store, self.policy.scoring)
                        self.deliberations.request(incident.incident_id, entity_id, "plan", assessment.model_dump(mode="json"), None)

    async def _save(self) -> None:
        """Commit everything this Brain knows. Called once a reading has been handled in full."""
        if self._state is None:
            return
        act = self._actuation
        reflex = {}
        for incident in self.triage.incidents.values():
            if incident.status == "open":
                values = (await self._graph.aget_state({"configurable": {"thread_id": incident.incident_id}})).values
                reflex[incident.incident_id] = {key: values[key] for key in ("levels", "scores", "pursued", "blocked", "actions") if key in values}
        self._state.save({
            "meta": {"saved_at": utcnow().isoformat(), "topology": self._topology_hash,
                     "position": self.twin.position() if hasattr(self.twin, "position") else None, **self._state.note},
            "store": self.store.snapshot(),
            "triage": self.triage.snapshot(),
            "perception": self.perception.snapshot(),
            "gate": act.gate.snapshot(),
            "actuation": {"decisions": act.decisions, "plans": [
                {"incident_id": incident_id, "entity_id": entity_id, "plan": plan} for (incident_id, entity_id), plan in act.plans.items()
            ]},
            "reflex": reflex,
            "deliberations": self.deliberations.snapshot() if self.deliberations else {},
        })

    async def _team_finished(self) -> None:
        """A team finished between readings: save now. During a reading, that reading's own save covers it."""
        if not self._handling:
            await self._save()

    async def run(self) -> None:
        """Consume the Twin's stream until it ends (only a mock's stream ever does).

        A Twin that cannot be reached is reported once and asked again every `twin.retry_s`; the adapter resumes after the last reading it
        handed over, so nothing is read twice, and what the Brain holds (incidents, units out, the gate's record) is untouched meanwhile.
        """
        retry = self.partners.twin.retry_s
        while True:
            try:
                async for raw in self.twin.stream_readings():
                    await self._twin_answered()
                    await self.handle(raw)
                    await self._recheck_capabilities()
                await self._twin_answered()
                return
            except TwinError as error:
                if retry <= 0:
                    raise
                if not self._twin_down:
                    self._twin_down = True
                    self.timeline.emit("brain.degraded", None, {
                        "component": "twin", "backend": self.partners.twin.adapter, "reason": f"{type(error).__name__}: {str(error)[:120]}",
                        "answering_from": "nothing new: no readings until the Twin answers; state is kept and nothing is sent twice"})
                await self._wait_for_twin(retry)

    async def _wait_for_twin(self, retry_s: float) -> None:
        while True:
            await asyncio.sleep(retry_s)
            try:
                await self.twin.get_topology()  # the cheapest question a Twin can answer
                return
            except TwinError:
                continue

    async def _twin_answered(self) -> None:
        if self._twin_down:
            self._twin_down = False
            self.timeline.emit("brain.recovered", None, {"component": "twin", "backend": self.partners.twin.adapter})

    async def _recheck_capabilities(self) -> None:
        """A Twin that adds or drops an actuator tool mid-run is reported. The gate keeps the list it read at start: a new tool is never used."""
        now = clock.current().now()
        if clock.current().deterministic or (now - self._capabilities_checked).total_seconds() < 60:
            return
        self._capabilities_checked = now
        try:
            current = set(await self.twin.list_capabilities())
        except Exception:  # a Twin that cannot say is not a change  # noqa: BLE001
            return
        if current != self._reported_capabilities:
            self.timeline.emit("brain.twin.capabilities.changed", None, {
                "added": sorted(current - self._capabilities), "removed": sorted(self._capabilities - current),
                "note": "the gate keeps using the list read at start"})
            self._reported_capabilities = current  # say it once per change

    async def run_until_quiet(self) -> None:
        """For scenario runs: keep going until the stream has ended and no team is still deliberating."""
        while True:
            await self.run()
            drained = [await d.drain() for d in (self.desks, self.deliberations) if d is not None]
            if not any(drained):
                return

    async def _team_started_pursuit(self, incident_id: str, entity_id: str, zone_id: str) -> None:
        """Tell the reflex graph a pursuit is under way, so it tracks instead of re-deciding."""
        await self._graph.aupdate_state({"configurable": {"thread_id": incident_id}}, {"pursued": {entity_id: zone_id}})

    async def handle(self, raw: Any) -> None:
        self._handling = True
        try:
            await self._handle(raw)
        finally:
            self._handling = False
        await self._save()

    async def _handle(self, raw: Any) -> None:
        try:
            perceived = self.perception.ingest(raw)
        except ContractError as error:
            if self.journal is not None and isinstance(raw, dict):
                self.journal.append("reading", **reading_record(raw, []), rejected=error.code)
            sensor = raw.get("sensor_id") if isinstance(raw, dict) else None
            if not (isinstance(sensor, str) and re.fullmatch(SAFE_ID, sensor)):
                sensor = None  # an id that failed the pattern is never echoed into the log or onto a screen
            self.timeline.emit("brain.reading.rejected", sensor, {"code": error.code, "message": error.message})
            return

        reading, value = perceived.reading, perceived.value
        if self.journal is not None:
            self.journal.append("reading", **reading_record(raw, perceived.dropped_fields))
        trace_id = f"{reading.sensor_id}:{reading.sequence_no}"
        clock.current().observe(reading.timestamp)  # a repeatable run is as old as the newest reading it has seen
        self.timeline.emit("brain.reading.received", reading.reading_id, {
            "type": reading.type, "zone_id": reading.zone_id, "sensor_id": reading.sensor_id,
            "summary": _summary(value),
            **({"entity_id": value.citizen_id} if isinstance(value, CitizenActivity) else {}),
            **({"dropped_fields": perceived.dropped_fields} if perceived.dropped_fields else {}),
        }, trace_id)

        verdict = await self._verdict(reading, raw, trace_id)
        self.timeline.emit("brain.verdict.received", reading.reading_id, {
            "verdict_id": verdict.verdict_id, "status": verdict.status.value, "reasons": verdict.reasons,
        }, trace_id)
        self.store.add_reading(reading, verdict)
        if self.recorder is not None:
            self.recorder.note_reading(reading)

        if isinstance(value, CitizenActivity):
            self.store.add_sighting(reading, value)
        if isinstance(value, UnitStatus):
            await self._unit_status(value, verdict, reading, trace_id)

        await self.bus.publish(Percept(reading, value, verdict, trace_id))
        await self._prewarn(reading, trace_id)

        incident_ids, opened = self.triage.on_reading(reading, value)
        if opened is not None:
            self.timeline.emit("brain.incident.opened", opened.incident_id, {
                "type": opened.type, "zone_id": opened.zone_id, "evidence": opened.evidence,
                "evidence_verdict": verdict.status.value, "departments": opened.departments,
            }, trace_id)
        for incident_id in self.triage.cleared_by(reading, value):
            if verdict.status != VerdictStatus.TRUSTED:
                continue  # an unvouched "all clear" ends nothing
            closed = self.triage.close(incident_id, "cleared")
            if closed is not None:
                self.store.close_incident(closed)
                self.timeline.emit("brain.incident.closed", closed.incident_id, {
                    "outcome": "cleared", "reading_id": reading.reading_id,
                }, trace_id)
                await self.bus.publish(IncidentClosed(closed.incident_id, "cleared", trace_id))
        if not incident_ids and verdict.status == VerdictStatus.TRUSTED and (unknown := self.triage.unrecognised(reading, value)) is not None:
            self.timeline.emit("brain.human.needed", reading.reading_id, {
                "why": "unknown_type", "type": unknown, "zone_id": reading.zone_id,
                "detail": f"a trusted {unknown.replace(':', ' reading of ')} arrived and no department recognises it, so no incident was opened"}, trace_id)
        for stalled in self.triage.stalled(reading.timestamp):
            last = max((x.timestamp for rid in stalled.evidence if (x := self.store.reading(rid)) is not None), default=stalled.occurred_at)
            self.timeline.emit("brain.human.needed", stalled.incident_id, {
                "why": "stalled", "type": stalled.type, "zone_id": stalled.zone_id,
                "detail": f"no new evidence for {round((reading.timestamp - last).total_seconds())} s and the incident is still open"}, trace_id)
        await self.bus.publish(IncidentTouched(tuple(incident_ids), trace_id, reading.timestamp))
        if self.desks is not None:
            for incident_id in incident_ids:  # a desk reviews an incident when it opens and again whenever a new independent source joins it
                incident = self.triage.incidents.get(incident_id)
                if incident is not None and incident.type != "crime" and incident.status == "open":
                    sources = sorted({r.split("#")[0] for r in incident.evidence})
                    self.desks.request(incident_id, incident_id, "desk", {"evidence_reading_ids": sources}, trace_id)
        for incident_id in incident_ids:
            await self._graph.ainvoke(
                {"incident_id": incident_id, "trace_id": trace_id},
                config={"configurable": {"thread_id": incident_id}},
            )
        if self.desks is not None:
            await self.desks.head_start(self.models.team.head_start_s)
        if self.deliberations is not None:
            await self.deliberations.head_start(self.models.team.head_start_s)

    async def reoffer(self, pending_id: str) -> list[dict[str, Any]]:
        """A person has answered a pending approval: put the held call back through the gate, which checks everything again."""
        proposal, trace_id = self.approvals.proposal(pending_id)
        act = self._actuation
        approved, _ = await gate_proposals(act, [proposal.model_dump(mode="json")], [], trace_id)
        return await execute_approvals(act, approved, trace_id)

    async def _verdict(self, reading: SensorReading, raw: dict[str, Any], trace_id: str) -> TrustVerdict:
        guardian = self.partners.guardian
        if guardian.mode == "inline" and reading.trust is not None:
            return reading.trust
        try:
            verdict = await self.guardian.get_verdict(raw, guardian.verdict_deadline_ms / 1000)
        except GuardianUnavailable as error:
            if self._guardian_up:
                self._guardian_up = False
                self.timeline.emit("brain.guardian.unavailable", None, {
                    "error": str(error), "mode": "degraded: no medium- or high-impact action until verdicts return",
                }, trace_id)
            return TrustVerdict(
                verdict_id=f"unavailable-{reading.reading_id}",
                reading_ref=ReadingRef(sensor_id=reading.sensor_id, sequence_no=reading.sequence_no),
                status=VerdictStatus.UNAVAILABLE, confidence=0.0,
                reasons=["guardian_unavailable"], issued_at=utcnow(),
            )
        if not self._guardian_up:
            self._guardian_up = True
            self.timeline.emit("brain.guardian.recovered", None, {}, trace_id)
        return verdict

    async def _unit_returned(self, status: UnitStatus, reading: SensorReading, trace_id: str) -> None:
        """A unit says it has finished and is on its way back: it is no longer out. When it was the last unit out for a
        fire or an accident (which have no other way to end), the incident is over."""
        act = self._actuation
        unit = next((u for u in self.store.units_out() if u["unit_id"] == status.unit_id), None)
        if unit is None:
            return  # already home: it was recalled, or it finished a chase the incident's closing took care of
        released = self.store.release_unit(status.unit_id)
        if released is not None:
            act.gate.release(released.get("key"))
            self.timeline.emit("brain.units.released", status.incident_id, {
                "cause": f"{status.unit_id} reported returning ({reading.reading_id})",
                "units": [{**{k: released.get(k) for k in ("unit_id", "mode", "zone_id", "actuator_id")}, "recalled": False}],
            }, trace_id)
        incident = self.triage.incidents.get(status.incident_id)
        if incident is None or incident.status != "open" or incident.type == "crime" or self.store.units_out(status.incident_id):
            return
        closed = self.triage.close(status.incident_id, "returned")
        if closed is not None:
            self.store.close_incident(closed)
            self.timeline.emit("brain.incident.closed", closed.incident_id, {"outcome": "returned", "unit_id": status.unit_id}, trace_id)
            await self.bus.publish(IncidentClosed(closed.incident_id, "returned", trace_id))

    async def _unit_status(self, status: UnitStatus, verdict: TrustVerdict, reading: SensorReading, trace_id: str) -> None:
        self.timeline.emit("brain.unit.status", status.incident_id, {
            "unit_id": status.unit_id, "state": status.state, "zone_id": reading.zone_id, "verdict": verdict.status.value,
        }, trace_id)
        if status.state == "returning" and verdict.status == VerdictStatus.TRUSTED:
            await self._unit_returned(status, reading, trace_id)
            return
        if status.state not in ("apprehended", "lost") or verdict.status != VerdictStatus.TRUSTED:
            return
        closed = self.triage.close(status.incident_id, status.state)
        if closed is None:
            return
        self.store.close_incident(closed)
        self.timeline.emit("brain.incident.closed", closed.incident_id, {
            "outcome": status.state, "unit_id": status.unit_id,
        }, trace_id)
        await self.bus.publish(IncidentClosed(closed.incident_id, status.state, trace_id))

        # Nothing is left to contain: bring back every unit still out for this incident.
        act = self._actuation
        for key in [key for key in act.plans if key[0] == closed.incident_id]:
            del act.plans[key]
        out = self.store.units_out(closed.incident_id)
        await stand_down(
            act, closed, [u for u in out if u["unit_id"] != status.unit_id], scope="closed", reading_id=reading.reading_id,
            cause=f"Incident {closed.incident_id} closed ({status.state.replace('_', ' ')}, {reading.reading_id})",
            trace_id=trace_id, returned=[u for u in out if u["unit_id"] == status.unit_id],
        )
