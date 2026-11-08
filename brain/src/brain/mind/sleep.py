"""Sleep: quiet-time learning. Mine episodes for plans the team made the same way more than once, rehearse
each as a candidate reflex against the real team, and promote it only through a gate.

What can be learned is narrow on purpose: a *cache of a verified deliberation*, written as a deterministic
`plan` rule. It never reads whether a dispatch worked, never names a person or a unit, and can only
propose actions the Police pack already allows (the gate still checks every one).
"""

from __future__ import annotations

import json
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from brain.baseline import MODELS, measure_scenario
from brain.config import BrainConfig, ModelsConfig, PartnersConfig, Policy
from brain.contracts import PARAM_MODELS
from brain.departments import Rule, discover_manifests
from brain.mind.episodes import Episode, EpisodeStore
from brain.mind.lifecycle import review
from brain.scenario import load_scenario
from brain.timeline import Timeline

# What a compiled plan may contain. A pursuit names a person, a recall names a unit, the rest is high impact.
ALLOWED_MODES = {"contain", "respond"}


@dataclass
class Candidate:
    rule: dict[str, Any]
    signature: tuple[str, str, str]  # incident zone, the suspect's last zone, the zone they were heading to ("" if none)
    sources: list[str]


def _allowed(action: dict[str, Any]) -> bool:
    if action["action"] == "broadcast_alert":
        return True
    return action["action"] == "dispatch_unit" and action["params"].get("mode") in ALLOWED_MODES and action["params"].get("unit_type") == "police"


def _fingerprint(episode: Episode) -> tuple[str, ...]:
    plan = next(p for p in episode.plans if p.reason == "plan")
    return tuple(json.dumps({"action": a.action, "params": a.params}, sort_keys=True) for a in plan.actions)


def _template(step: dict[str, Any]) -> dict[str, Any]:
    params = dict(step["params"])
    if step["action"] == "dispatch_unit":
        params["incident_id"] = "$incident.incident_id"
        if params.get("mode") == "contain":
            params["target_id"] = "$assessment.entity_id"
    return {"action": step["action"], "params": params}


def mine(episodes: list[Episode], min_support: int) -> list[Candidate]:
    """One candidate for each pattern whose most common plan was made at least `min_support` times, with no tie."""
    groups: dict[tuple[str, str, str], list[Episode]] = defaultdict(list)
    for episode in episodes:
        if episode.incident.type != "crime" or len(episode.pursuits) != 1 or not any(p.reason == "plan" for p in episode.plans):
            continue
        pursuit = episode.pursuits[0]
        groups[(episode.incident.zone_id, pursuit.zone_id, pursuit.heading_zone_id or "")].append(episode)

    candidates = []
    for signature, members in sorted(groups.items()):
        if not all(_allowed(json.loads(step)) for member in members for step in _fingerprint(member)):
            continue  # one episode that tried something a lesson may not do spoils the whole pattern
        counts = Counter(_fingerprint(member) for member in members)
        (best, support), *rest = counts.most_common()
        if support < min_support or (rest and rest[0][1] == support):
            continue
        sources = [m.episode_id for m in members if _fingerprint(m) == best]
        zone, last, heading = signature
        when = {"incident.type": "crime", "incident.zone_id": zone, "assessment.level": "suspect", "assessment.last_zone_id": last,
                "assessment.heading_zone_id": heading or None}
        candidates.append(Candidate(
            rule={
                "id": f"CAND-{len(candidates) + 1}", "name": f"learned.plan.{zone}.{last}.{heading or 'none'}", "scope": "plan",
                "description": f"A plan the team made {support} times for a crime in {zone} with the suspect last seen in {last}"
                               + (f" heading to {heading}." if heading else "."),
                "when": when, "do": [_template(json.loads(step)) for step in best],
                "learned": {"sources": sources, "support": support},
            },
            signature=signature, sources=sources,
        ))
    return candidates


# ---------------------------------------------------------------------------- rehearsal and the promotion gate

DEFAULT_SUITE = ["t12", "t13", "t14", "t15"]
DEFAULT_HELD_OUT = ["t13", "t15"]  # scenarios no lesson is taught from; reported on their own
COMPARED = ("decisions", "blocked")


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class SleepReport:
    episodes: int = 0
    unreadable: int = 0
    candidates: int = 0
    crew: str = "scripted"
    promoted: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    revoked: list[str] = field(default_factory=list)
    retired: list[dict[str, Any]] = field(default_factory=list)  # faded or contradicted: see lifecycle.py
    seconds: float = 0.0


def replay_scenario(episode: Episode, topology: dict[str, Any], heading_change: tuple[str, str | None] | None = None) -> dict[str, Any]:
    """An episode as a scenario the mock Twin can play: its readings in order, at their offsets, all believed.

    `heading_change=(old, new)` rewrites every sighting heading to `old` as heading to `new` (or to nowhere):
    a variant of the same story that should *not* match the lesson.
    """
    events = []
    for reading in episode.readings:
        value = dict(reading.value)
        if heading_change and value.get("heading_zone_id") == heading_change[0]:
            value["heading_zone_id"] = heading_change[1]
        events.append({"at_ms": reading.at_ms, "sensor_id": reading.sensor_id, "type": reading.type, "zone_id": reading.zone_id, "value": value})
    return {"id": f"replay-{episode.episode_id}", "topology": topology, "guardian": {"default": "trusted"}, "events": events}


def _differences(without: dict[str, Any], with_rule: dict[str, Any]) -> list[str]:
    return [key for key in COMPARED if without[key] != with_rule[key]]


class Sleeper:
    def __init__(
        self, episodes_dir: Path, learned_dir: Path, policy: Policy, timeline: Timeline, *,
        suite: list[str] | None = None, held_out: list[str] | None = None, models: ModelsConfig | None = None,
    ) -> None:
        self.episodes = EpisodeStore(episodes_dir)
        self.learned_dir = learned_dir
        self.policy = policy
        self.timeline = timeline
        self.suite = DEFAULT_SUITE if suite is None else suite
        self.held_out = DEFAULT_HELD_OUT if held_out is None else held_out
        self.models = models or MODELS
        self._cache: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}

    # ---- running the Brain with a set of learned rules, in simulation

    async def _measure(self, key: str, scenario: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any]:
        cache_key = (key, tuple(r["id"] + json.dumps(r["do"], sort_keys=True) for r in rules))
        if cache_key not in self._cache:
            with tempfile.TemporaryDirectory(prefix="rehearsal-") as folder:
                (Path(folder) / "rules.yaml").write_text(yaml.safe_dump({"rules": rules}, sort_keys=False))
                partners = PartnersConfig(brain=BrainConfig(learned_dir=folder))
                self._cache[cache_key] = await measure_scenario(scenario, self.policy, partners, self.models)
        return self._cache[cache_key]

    def _promoted_rules(self) -> list[dict[str, Any]]:
        path = self.learned_dir / "rules.yaml"
        return (yaml.safe_load(path.read_text()) or {}).get("rules", []) if path.is_file() else []

    # ---- the gate

    def _provenance(self, sources: list[Episode], retracted: set[str]) -> CheckResult:
        bad = sorted({r.reading_id for e in sources for r in e.readings if r.verdict != "trusted" or r.reading_id in retracted})
        if bad:
            return CheckResult("provenance", False, f"{len(bad)} source readings are not trusted or were retracted ({', '.join(bad[:3])})")
        return CheckResult("provenance", True, f"every reading in {len(sources)} episodes was trusted and none retracted")

    def _safety(self, candidate: Candidate) -> CheckResult:
        police = discover_manifests()[0]["POLICE"]
        try:
            rule = Rule.model_validate({**candidate.rule, "department": "POLICE"})
            for step in rule.do:
                # Stand-ins for what `$incident.incident_id` and `$assessment.entity_id` become when the rule fires.
                params = {k: ("inc-0000" if k == "incident_id" else "p-0" if k == "target_id" else v) for k, v in step.params.items()}
                PARAM_MODELS[step.action].model_validate(params)
                if not police.allows(step.action, params) or not _allowed({"action": step.action, "params": params}):
                    return CheckResult("safety", False, f"{step.action} {step.params} is not something a lesson may do")
        except (ValidationError, KeyError) as error:
            return CheckResult("safety", False, f"the rule does not validate: {str(error).splitlines()[0]}")
        return CheckResult("safety", True, "only contain, respond and alert, all inside the Police allowlist")

    def _cap(self) -> CheckResult:
        have, cap = len(self._promoted_rules()), self.policy.learning.max_learned_rules
        return CheckResult("cap", have < cap, f"{have} learned rules of {cap} allowed")

    async def _rehearse(self, candidate: Candidate, sources: list[Episode], existing: list[dict[str, Any]]) -> CheckResult:
        """Replay each source episode with the candidate loaded: the decisions must be the team's, and the team need not run."""
        rule = candidate.rule
        for episode in sources:
            if not episode.topology:
                return CheckResult("rehearsal", False, f"{episode.episode_id} has no city layout saved")
            scenario = replay_scenario(episode, self.episodes.topology(episode.topology))
            without = await self._measure(episode.episode_id, scenario, existing)
            taught = await self._measure(episode.episode_id, scenario, [*existing, rule])
            if (moved := _differences(without, taught)):
                return CheckResult("rehearsal", False, f"replaying {episode.episode_id}, the team decides differently from the lesson ({', '.join(moved)})")
            if taught["compiled_plans"] < 1 or taught["deliberations"] >= without["deliberations"]:
                return CheckResult("rehearsal", False, f"the lesson did not replace a team run when replaying {episode.episode_id}")
        return CheckResult("rehearsal", True, f"replayed {len(sources)} episodes: same decisions, fewer team runs")

    async def _variants(self, candidate: Candidate, sources: list[Episode], existing: list[dict[str, Any]]) -> CheckResult:
        """Neighbouring stories (the suspect heading somewhere else) must be left to the team."""
        tried = 0
        for episode in sources:
            heading = episode.pursuits[0].heading_zone_id if episode.pursuits else None
            if not heading or not episode.topology:
                continue
            topology = self.episodes.topology(episode.topology)
            neighbours = sorted({b if a == heading else a for a, b in topology.get("adjacency", []) if heading in (a, b)})
            for other in [*neighbours[:3], None]:
                scenario = replay_scenario(episode, topology, (heading, other))
                key = f"{episode.episode_id}->{other}"
                without = await self._measure(key, scenario, existing)
                taught = await self._measure(key, scenario, [*existing, candidate.rule])
                tried += 1
                if taught["compiled_plans"]:
                    return CheckResult("variants", False, f"the lesson fired when the suspect headed to {other or 'nowhere'} instead of {heading}")
                if (moved := _differences(without, taught)):
                    return CheckResult("variants", False, f"a variant ({other or 'no heading'}) changed {', '.join(moved)}")
        return CheckResult("variants", True, f"{tried} neighbouring stories left to the team")

    async def check_suite(self, rule: dict[str, Any], existing: list[dict[str, Any]]) -> list[str]:
        """Scenarios whose decisions change when `rule` is loaded. Held-out ones are marked."""
        moved = []
        for scenario_id in self.suite:
            scenario = load_scenario(scenario_id)
            without = await self._measure(scenario_id, scenario, existing)
            taught = await self._measure(scenario_id, scenario, [*existing, rule])
            if _differences(without, taught):
                moved.append(scenario_id + (" (held out)" if scenario_id in self.held_out else ""))
        return moved

    async def _suite(self, candidate: Candidate, existing: list[dict[str, Any]]) -> CheckResult:
        moved = await self.check_suite(candidate.rule, existing)
        if moved:
            return CheckResult("suite", False, f"decisions change in {', '.join(moved)}")
        return CheckResult("suite", True, f"{len(self.suite)} scenarios decide as before ({len(self.held_out)} held out)")

    # ---- the job

    def _emit(self, kind: str, subject: str | None, data: dict[str, Any]) -> None:
        self.timeline.emit(f"brain.sleep.{kind}", subject, data)

    def _retractions(self) -> set[str]:
        path = self.learned_dir / "retractions.jsonl"
        if not path.is_file():
            return set()
        return {json.loads(line)["reading_id"] for line in path.read_text().splitlines() if line.strip()}

    def _retired_sources(self) -> dict[tuple, set[str]]:
        """Patterns a rule was retired for (faded or contradicted) and the episodes that taught it: not to be learned again from those alone."""
        path = self.learned_dir / "rejected.jsonl"
        found: dict[tuple, set[str]] = {}
        if path.is_file():
            for line in path.read_text().splitlines():
                entry = json.loads(line) if line.strip() else {}
                if entry.get("check") in ("faded", "contradicted") and entry.get("signature"):
                    found.setdefault(tuple(entry["signature"]), set()).update(entry.get("sources") or [])
        return found

    async def run(self, dry_run: bool = False) -> SleepReport:
        started = time.monotonic()
        episodes, unreadable = self.episodes.all()
        report = SleepReport(episodes=len(episodes), unreadable=unreadable)
        self._emit("started", None, {"episodes": len(episodes), "unreadable": unreadable, "promoted_before": len(self._promoted_rules())})
        retracted = self._retractions()
        by_id = {e.episode_id: e for e in episodes}

        existing = self._promoted_rules()
        for rule in list(existing):
            taught_by = [by_id[i] for i in (rule.get("learned") or {}).get("sources", []) if i in by_id]
            tainted = sorted({r.reading_id for e in taught_by for r in e.readings if r.reading_id in retracted})
            if tainted:
                existing.remove(rule)
                report.revoked.append(rule["id"])
                entry = {"rule": rule["id"], "signature": rule["learned"].get("signature"), "sources": rule["learned"].get("sources"),
                         "check": "revoked", "reason": f"the Guardian retracted {', '.join(tainted[:3])}, which taught it", "checks": []}
                self._emit("rule.rejected", rule["id"], entry)
                if not dry_run:
                    self.learned_dir.mkdir(parents=True, exist_ok=True)
                    with (self.learned_dir / "rejected.jsonl").open("a") as file:
                        file.write(json.dumps({**entry, "at": datetime.now(UTC).isoformat()}) + "\n")
        # The life of what was learned: confirmed, idle, or contradicted since it was made. Retracted episodes teach nothing.
        usable = [e for e in episodes if not any(r.reading_id in retracted for r in e.readings)]
        before = existing
        existing, retired = review(existing, usable, self.policy.learning)
        for entry in retired:
            report.retired.append(entry)
            self._emit("rule.rejected", entry["rule"], {**entry, "checks": []})
            if not dry_run:
                self.learned_dir.mkdir(parents=True, exist_ok=True)
                with (self.learned_dir / "rejected.jsonl").open("a") as file:
                    file.write(json.dumps({**entry, "at": datetime.now(UTC).isoformat()}) + "\n")
        if (report.revoked or retired or existing != before) and not dry_run:
            self._write(existing)
        learned_signatures = {
            (r["when"].get("incident.zone_id"), r["when"].get("assessment.last_zone_id"), r["when"].get("assessment.heading_zone_id") or "")
            for r in existing
        }
        candidates = mine(usable, self.policy.learning.min_support)
        report.candidates = len(candidates)
        retired_before = self._retired_sources()
        for candidate in candidates:
            subject = candidate.rule["name"]
            if candidate.signature in learned_signatures:
                report.skipped.append({"signature": candidate.signature, "reason": "already learned"})
                continue
            if set(candidate.sources) <= retired_before.get(candidate.signature, set()) | {s for e in report.retired if tuple(e["signature"]) == candidate.signature for s in e["sources"]}:
                report.skipped.append({"signature": candidate.signature, "reason": "retired, and nothing new supports it"})
                continue
            self._emit("rule.proposed", subject, {"signature": list(candidate.signature), "sources": candidate.sources, "support": len(candidate.sources)})
            sources = [by_id[i] for i in candidate.sources]
            results: list[CheckResult] = []
            for check in (lambda: self._provenance(sources, retracted), lambda: self._safety(candidate), self._cap,
                          lambda: self._rehearse(candidate, sources, existing), lambda: self._variants(candidate, sources, existing),
                          lambda: self._suite(candidate, existing)):
                outcome = check()
                result = await outcome if hasattr(outcome, "__await__") else outcome
                results.append(result)
                if not result.passed:
                    break
            failed = results[-1] if not results[-1].passed else None
            if failed is not None:
                entry = {"rule": subject, "signature": list(candidate.signature), "sources": candidate.sources, "check": failed.name,
                         "reason": failed.detail, "checks": [r.name for r in results[:-1]]}
                report.rejected.append(entry)
                self._emit("rule.rejected", subject, entry)
                if not dry_run:
                    self.learned_dir.mkdir(parents=True, exist_ok=True)
                    with (self.learned_dir / "rejected.jsonl").open("a") as file:
                        file.write(json.dumps({**entry, "at": datetime.now(UTC).isoformat()}) + "\n")
                continue
            number = 1 + max([int(r["id"].split("-")[1]) for r in existing] + [0])
            promoted = {**candidate.rule, "id": f"LRN-{number}", "learned": {
                **candidate.rule["learned"], "signature": list(candidate.signature), "created": datetime.now(UTC).isoformat(),
                "crew": "llm" if self.models.team.llm else "scripted", "checks": [r.name for r in results],
            }}
            entry = {"rule": promoted["id"], "name": subject, "signature": list(candidate.signature), "sources": candidate.sources,
                     "checks": [{"name": r.name, "detail": r.detail} for r in results]}
            report.promoted.append(entry)
            self._emit("rule.promoted", promoted["id"], entry)
            existing = [*existing, promoted]
            learned_signatures.add(candidate.signature)
            if not dry_run:
                self._write(existing)
        report.seconds = round(time.monotonic() - started, 2)
        self._emit("finished", None, {"promoted": len(report.promoted), "rejected": len(report.rejected), "skipped": len(report.skipped),
                                      "seconds": report.seconds})
        if not dry_run:
            self.learned_dir.mkdir(parents=True, exist_ok=True)
            (self.learned_dir / "last-sleep.json").write_text(json.dumps(
                {"at": datetime.now(UTC).isoformat(), "episodes": report.episodes, "unreadable": report.unreadable,
                 "candidates": report.candidates, "promoted": report.promoted, "rejected": report.rejected, "skipped": report.skipped,
                 "seconds": report.seconds}, indent=2, default=list) + "\n")
        return report

    def _write(self, rules: list[dict[str, Any]]) -> None:
        self.learned_dir.mkdir(parents=True, exist_ok=True)
        (self.learned_dir / "rules.yaml").write_text(
            "# Written by `brain sleep`. Each rule is a cache of a plan the team made and the gate approved; delete a rule\n"
            "# or run `brain sleep --rollback` to forget it. Nothing here may name a person or a unit.\n"
            + yaml.safe_dump({"rules": rules}, sort_keys=False, width=120))
        (self.learned_dir / "manifest.json").write_text(json.dumps({"rules": [
            {"id": r["id"], **{key: (r.get("learned") or {}).get(key) for key in ("created", "sources", "support", "signature", "checks", "crew",
                                                                                   "confirmed", "contradicted", "uses", "sleeps_idle")}}
            for r in rules]}, indent=2) + "\n")


async def sleep(
    episodes_dir: Path, learned_dir: Path, policy: Policy, timeline: Timeline, *, suite: list[str] | None = None,
    held_out: list[str] | None = None, models: ModelsConfig | None = None, dry_run: bool = False,
) -> SleepReport:
    return await Sleeper(episodes_dir, learned_dir, policy, timeline, suite=suite, held_out=held_out, models=models).run(dry_run)


def rollback(learned_dir: Path, which: str = "all") -> list[str]:
    """Forget learned rules: one by id, or all. Returns the ids removed. The history file keeps what was done."""
    path = learned_dir / "rules.yaml"
    if not path.is_file():
        return []
    rules = (yaml.safe_load(path.read_text()) or {}).get("rules", [])
    gone = [r["id"] for r in rules if which in ("all", r["id"])]
    kept = [r for r in rules if r["id"] not in gone]
    sleeper = Sleeper(learned_dir, learned_dir, Policy(), Timeline([]))
    sleeper._write(kept)
    with (learned_dir / "history.jsonl").open("a") as file:
        file.write(json.dumps({"action": "rollback", "removed": gone, "at": datetime.now(UTC).isoformat()}) + "\n")
    return gone
