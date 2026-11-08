"""The Academy: the Brain improves its own parameters, inside a fence, one step at a time.

It never touches anything that is not on the tunable surface (`surface.py`), never reads whether a dispatch worked,
and never reads live data: it is scored on a fixed battery of synthetic sensor streams with a known truth and on the
burst scenarios of the Test Book. A proposal is one parameter moved one step. It is promoted only if

  * it lowers the loss on the design stories by a real margin,
  * it also lowers it on stories it was not tuned on (held-out seeds, variants of the burst scenarios),
  * and every hard constraint still holds: the Test Book decides exactly as before, held-out variants decide as their
    base, no spike is adopted, a spike is still reported after a walked threshold, no injected anomaly that the
    untuned Brain reported goes unreported, and the timelines keep their temporal promises.

A promoted value is written to an overlay the Brain loads over its policy, with the evidence, and can be undone with
`rollback`. `audit` re-scores what was promoted on new stories and retires what does not survive them. The search
is local, greedy and deterministic; what it adapts is its own reach: it only ever tries the neighbours of what it has.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from brain import config
from brain.baseline import MODELS, differences, measure_all
from brain.config import Policy
from brain.mind.attention_report import attention_report
from brain.mind.forward_bench import recall, score
from brain.mind.specs import verify_log
from brain.mind.surface import SURFACE, apply_overlay, load_overlay, save_overlay
from brain.scenario import DEV_SECRETS, expand_streams, inproc_partners, load_raw_scenario, load_scenario, run_scenario
from brain.variants import check, variants

DESIGN_SEEDS = range(0, 5)
HELD_OUT_SEEDS = range(1000, 1005)
FRESH_SEEDS = range(1005, 1010)  # what the self-audit scores on: stories nothing has been tuned or confirmed on
BURSTS = ("d4",)
CALM_STREAMS = ("calm", "noisy", "heavy", "skewed", "season")
MISS_COST = 20.0  # one missed anomaly costs as much as twenty false doubts per thousand readings: the Academy may not go deaf


@dataclass
class Evaluation:
    loss: float
    parts: dict[str, float] = field(default_factory=dict)


class Scorer(Protocol):
    async def design(self, policy: Policy) -> Evaluation: ...
    async def held_out(self, policy: Policy) -> Evaluation: ...
    async def constraints(self, policy: Policy) -> dict[str, tuple[bool, str]]: ...


@dataclass
class AcademyReport:
    promoted: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    start_loss: float = 0.0
    end_loss: float = 0.0


class Battery:
    """The real scoring battery. Everything in it is synthetic or a Test Book scenario: nothing is read from a live city."""

    def __init__(self, fresh: bool = False) -> None:
        self._seeds = FRESH_SEEDS if fresh else HELD_OUT_SEEDS
        self._untuned_recall: dict[str, float] = {}

    @staticmethod
    def _forward(policy: Policy, seeds) -> tuple[float, dict[str, float]]:
        scores = score(policy.forward, seeds)
        false_doubts = sum(scores[name]["false_doubts_per_1000"] for name in CALM_STREAMS) / len(CALM_STREAMS)
        missed = 1.0 - recall(policy.forward, seeds)
        return false_doubts + MISS_COST * missed, {"false_doubts_per_1000": round(false_doubts, 3), "missed_anomalies": round(missed, 4)}

    @staticmethod
    async def _attention(policy: Policy, scenarios: list[dict[str, Any]]) -> tuple[float, dict[str, float]]:
        for name, value in DEV_SECRETS.items():
            os.environ.setdefault(name, value)
        total = {"denied": 0.0, "inversions": 0.0, "longest_wait": 0.0}
        for scenario in scenarios:
            result = await run_scenario(scenario, inproc_partners(), policy=policy, models=MODELS, speed=0, timeout_s=30)
            report = attention_report(result.sink.events)
            total["denied"] += report["denied"]
            total["inversions"] += report["inversions"]
            total["longest_wait"] += report["longest_wait_readings"]
        n = len(scenarios) or 1
        loss = (total["denied"] + 0.5 * total["inversions"] + total["longest_wait"] / 20) / n
        return loss, {key: round(value / n, 3) for key, value in total.items()}

    async def design(self, policy: Policy) -> Evaluation:
        forward, f_parts = self._forward(policy, DESIGN_SEEDS)
        attention, a_parts = await self._attention(policy, [load_scenario(sid) for sid in BURSTS])
        return Evaluation(forward + attention, {**f_parts, **a_parts})

    async def held_out(self, policy: Policy) -> Evaluation:
        forward, f_parts = self._forward(policy, self._seeds)
        scenarios = []
        for sid in BURSTS:
            raw = load_raw_scenario(sid)
            scenarios += [expand_streams({k: v for k, v in v.items() if k not in ("variant_of", "transform", "seed")})
                          for v in variants(raw, [self._seeds[0], self._seeds[1]])]
        attention, a_parts = await self._attention(policy, scenarios)
        return Evaluation(forward + attention, {**f_parts, **a_parts})

    async def constraints(self, policy: Policy) -> dict[str, tuple[bool, str]]:
        out: dict[str, tuple[bool, str]] = {}
        frozen = json.loads((config.home() / "docs/baseline/2026-11-07-demo-frozen.json").read_text())
        moved = differences(frozen, await measure_all(list(frozen), policy=policy))
        out["decisions"] = (not moved, "every Test Book decision as before" if not moved else f"{len(moved)} changed, first: {moved[0][:90]}")
        rows = await check(["d2", "d3", "d4"], [self._seeds[0]], policy=policy)
        off = [r for r in rows if not r["passed"]]
        out["variants"] = (not off, f"{len(rows)} variants decide as their base" if not off else f"{len(off)} differ, first {off[0]['scenario']} {off[0]['transform']}")
        bench = score(policy.forward, self._seeds)
        sound = bench["spike"]["spike_adopted"] == 0 and bench["walk"]["walk_spike_reported"] == 1 and bench["step_l"]["delay"] is not None
        out["forward invariants"] = (sound, "no spike adopted, a walked threshold still reports a spike, a step is accepted" if sound else f"broken: {bench['spike']}, {bench['walk']}")
        if "now" not in self._untuned_recall:
            self._untuned_recall["now"] = recall(Policy().forward, DESIGN_SEEDS)
        seen = recall(policy.forward, DESIGN_SEEDS)
        out["recall"] = (seen >= self._untuned_recall["now"] - 1e-9, f"{seen:.3f} of injected anomalies reported (untuned {self._untuned_recall['now']:.3f})")
        broken = []
        for sid in BURSTS + ("d3",):
            result = await run_scenario(load_scenario(sid), inproc_partners(), policy=policy, models=MODELS, speed=0, timeout_s=30)
            broken += verify_log(result.sink.events)
        out["promises"] = (not broken, "the temporal promises hold" if not broken else f"{broken[0].spec}: {broken[0].message}")
        return out


def _value(policy: Policy, path: str) -> float:
    node: Any = policy
    for part in path.split("."):
        node = node[part] if isinstance(node, dict) else getattr(node, part)
    return float(node)


def _log(folder: Path, entry: dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "history.jsonl").open("a", encoding="utf-8") as file:
        file.write(json.dumps({**entry, "at": datetime.now(UTC).isoformat(timespec="seconds")}) + "\n")


class Academy:
    def __init__(self, folder: Path, scorer: Scorer | None = None, policy: Policy | None = None, *, max_changes: int = 6, min_gain: float = 0.005) -> None:
        self.folder = Path(folder)
        self.scorer = scorer or Battery()
        self.base = policy or Policy()
        self.max_changes, self.min_gain = max_changes, min_gain

    def _overlay_with(self, overlay: dict[str, float], path: str, value: float) -> dict[str, float]:
        merged = {**overlay, path: round(value, 6)}
        if abs(merged[path] - _value(self.base, path)) < 1e-9:
            merged.pop(path)  # back at the shipped value: no longer a change
        return merged

    async def run(self, steps: int = 20, dry_run: bool = False) -> AcademyReport:
        overlay, _ = load_overlay(self.folder)
        current = apply_overlay(self.base, overlay)
        design, held = await self.scorer.design(current), await self.scorer.held_out(current)
        report = AcademyReport(start_loss=design.loss, end_loss=design.loss)
        for step in range(steps):
            report.steps = step + 1
            candidates = []
            for path, tunable in SURFACE.items():
                now = _value(current, path)
                for direction in (1, -1):
                    value = now + direction * tunable.step
                    if not tunable.low - 1e-9 <= value <= tunable.high + 1e-9:
                        continue
                    proposal = self._overlay_with(overlay, path, value)
                    if len(proposal) > self.max_changes:
                        continue
                    policy = apply_overlay(self.base, proposal)
                    evaluation = await self.scorer.design(policy)
                    if evaluation.loss < design.loss - 1e-9:
                        candidates.append((evaluation.loss, path, round(value, 6), proposal, policy, evaluation))
            if not candidates:
                break
            promoted = False
            for loss, path, value, proposal, policy, evaluation in sorted(candidates, key=lambda c: (c[0], c[1], c[2]))[:3]:
                base_entry = {"path": path, "from": round(_value(current, path), 6), "to": value, "design_gain": round(design.loss - loss, 4)}
                if design.loss - loss < max(self.min_gain * design.loss, 0.01):
                    continue
                held_eval = await self.scorer.held_out(policy)
                base_entry["held_out_gain"] = round(held.loss - held_eval.loss, 4)
                if held.loss - held_eval.loss < max(self.min_gain * held.loss, 0.01):
                    self._reject(report, base_entry, "held-out", f"it gained {base_entry['design_gain']} on the design stories but {base_entry['held_out_gain']} on stories it was not tuned on", dry_run)
                    continue
                failed = {name: detail for name, (ok, detail) in (await self.scorer.constraints(policy)).items() if not ok}
                if failed:
                    name, detail = next(iter(failed.items()))
                    self._reject(report, base_entry, name, detail, dry_run)
                    continue
                overlay, current, design, held = proposal, policy, evaluation, held_eval
                report.promoted.append(base_entry)
                report.end_loss = design.loss
                if not dry_run:
                    save_overlay(self.folder, overlay, f"tuned {datetime.now(UTC).date().isoformat()}")
                    _log(self.folder, {"action": "promoted", **base_entry, "design_loss": round(design.loss, 4), "parts": evaluation.parts})
                promoted = True
                break
            if not promoted:
                break
        return report

    def _reject(self, report: AcademyReport, entry: dict[str, Any], check_name: str, reason: str, dry_run: bool) -> None:
        row = {**entry, "check": check_name, "reason": reason}
        report.rejected.append(row)
        if not dry_run:
            _log(self.folder, {"action": "rejected", **row})


def rollback(folder: Path, which: str = "all") -> list[str]:
    """Take one tuned parameter (or all of them) out of the overlay. The Brain is then exactly the earlier one."""
    overlay, _ = load_overlay(folder)
    gone = [path for path in overlay if which in ("all", path)]
    if not gone:
        return []
    kept = {path: value for path, value in overlay.items() if path not in gone}
    if kept:
        save_overlay(folder, kept, "rolled back")
    else:
        (Path(folder) / "overlay.yaml").unlink(missing_ok=True)
    for path in gone:
        _log(Path(folder), {"action": "rolled back", "path": path, "from": overlay[path], "to": None})
    return gone


def show(folder: Path) -> str:
    """The overlay, and the evidence the Academy wrote down for each value."""
    overlay, problem = load_overlay(folder)
    if problem:
        return f"The overlay is not usable: {problem}"
    if not overlay:
        return "No tuned values: the Brain runs exactly as shipped."
    history = [json.loads(line) for line in (Path(folder) / "history.jsonl").read_text().splitlines()] if (Path(folder) / "history.jsonl").is_file() else []
    lines = []
    for path, value in sorted(overlay.items()):
        proof = [h for h in history if h.get("path") == path and h.get("action") == "promoted"]
        last = proof[-1] if proof else {}
        lines.append(f"{path} = {value}  (shipped {_value(Policy(), path)}; design gain {last.get('design_gain')}, held-out gain {last.get('held_out_gain')})")
    return "\n".join(lines)


async def audit(folder: Path, scorer: Scorer | None = None) -> list[str]:
    """Score the tuned overlay on stories nothing was tuned or confirmed on, and retire every value that does not beat the shipped one there."""
    overlay, _ = load_overlay(folder)
    if not overlay:
        return []
    scorer = scorer or Battery(fresh=True)
    base = Policy()
    retired = []
    for path in sorted(overlay):
        alone = apply_overlay(base, {path: overlay[path]})
        tuned, shipped = await scorer.held_out(alone), await scorer.held_out(base)
        if tuned.loss >= shipped.loss - 1e-9:
            retired.append(path)
    for path in retired:
        rollback(folder, path)
        _log(Path(folder), {"action": "retired by audit", "path": path, "reason": "it no longer beats the shipped value on new stories"})
    return retired
