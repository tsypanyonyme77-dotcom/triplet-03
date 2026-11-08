"""Rehearsal: everything the freeze needs, run offline in one command, with a dated report.

It replays the Test Book, checks the baselines, measures the learning curve and the ablations, tries a poisoned
lesson, and proves it never reached for the network. The report is what the team keeps as evidence that the build
stands; it exits 1 on any failure, so it can gate the freeze.
"""

from __future__ import annotations

import json
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brain import config
from brain.baseline import differences, measure
from brain.config import Policy
from brain.mind.ablate import ablate, table
from brain.mind.curve import learning_curve
from brain.mind.episodes import EpisodeStore, PlanAction, PlanRecord
from brain.mind.sleep import DEFAULT_SUITE, Sleeper
from brain.timeline import MemorySink, Timeline

QUICK_SUITE = ["d1", "d2", "d3", "d4"]
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@dataclass
class Step:
    name: str
    passed: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Report:
    started: str
    steps: list[Step]
    seconds: float

    @property
    def passed(self) -> bool:
        return all(step.passed for step in self.steps)


@dataclass
class Context:
    quick: bool
    workdir: Path
    suite: list[str]
    blocked: list[str] = field(default_factory=list)


@contextmanager
def offline(blocked: list[str]):
    """Refuse any connection that is not to this machine, and remember each attempt."""
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else None
        if self.family != socket.AF_UNIX and host not in LOOPBACK:
            blocked.append(str(address))
            raise OSError(f"rehearsal is offline: refused to connect to {address}")
        return real_connect(self, address)

    socket.socket.connect = guarded  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]


async def run_test_book(context: Context) -> Step:
    failed = [sid for sid in context.suite if not (await measure(sid))["passed"]]
    return Step("Test Book", not failed, f"{len(context.suite) - len(failed)} of {len(context.suite)} scenarios pass"
                + (f"; failing: {', '.join(failed)}" if failed else ""))


async def baselines(context: Context) -> Step:
    docs = config.home() / "docs/baseline"
    frozen = {k: v for k, v in json.loads((docs / "2026-11-07-demo-frozen.json").read_text()).items() if k in context.suite}
    moved = differences(frozen, {sid: await measure(sid) for sid in frozen})
    return Step("Baselines", not moved, f"{len(frozen)} scenarios decide as frozen" if not moved else "; ".join(moved[:3]))


async def curve(context: Context) -> Step:
    rows = await learning_curve("d3", runs=3, workdir=context.workdir / "curve", policy=Policy(), suite=["d1", "d3"])
    first, third = rows[0], rows[-1]
    ok = third["team_runs"] < first["team_runs"] and all(r["decisions_equal_to_run_1"] for r in rows)
    return Step("Learning curve", ok, f"team runs {first['team_runs']} to {third['team_runs']}, last action {first['last_action_ms']} ms to "
                f"{third['last_action_ms']} ms, decisions identical: {all(r['decisions_equal_to_run_1'] for r in rows)}", {"rows": rows})


async def ablations(context: Context) -> Step:
    result = await ablate(context.suite, context.workdir / "ablate")
    cfg = result["configs"]
    checks = {
        "the full Brain is the reference": cfg["full"]["decisions_changed"] == [],
        "no bids changes no decision": cfg["no bids"]["decisions_changed"] == [],
        "no learned reflexes brings the team back": cfg["no learned reflexes"]["team_runs"] > cfg["full"]["team_runs"],
    }
    bad = [name for name, ok in checks.items() if not ok]
    return Step("Ablations", not bad, "every region moves a number" if not bad else f"did not hold: {'; '.join(bad)}", {"result": result, "table": table(result)})


async def poison(context: Context) -> Step:
    """Three trusted-looking episodes that all teach a nonsense perimeter must be turned away at rehearsal."""
    folder = context.workdir / "poison"
    from brain.baseline import measure_scenario
    from brain.config import BrainConfig, PartnersConfig
    from brain.scenario import load_scenario

    await measure_scenario(load_scenario("d3"), Policy(), PartnersConfig(brain=BrainConfig(episodes_dir=str(folder / "episodes"))))
    store = EpisodeStore(folder / "episodes")
    (real,), _ = store.all()
    nonsense = [PlanAction(action="dispatch_unit", params={"unit_type": "police", "zone_id": z, "mode": "contain"}) for z in ("zone-01", "zone-02")]
    for n in range(3):
        store.append(real.model_copy(update={"episode_id": f"ep-poison-{n}", "plans": [PlanRecord(reason="plan", actions=nonsense)]}))
    report = await Sleeper(folder / "episodes", folder / "learned", Policy(), Timeline([MemorySink()]), suite=["d1", "d3"], held_out=[]).run()
    ok = report.candidates == 1 and not report.promoted and [r["check"] for r in report.rejected] == ["rehearsal"]
    return Step("Poisoned lesson", ok, "three repeated nonsense plans were turned away at rehearsal, nothing written" if ok
                else f"promoted {len(report.promoted)}, rejected at {[r['check'] for r in report.rejected]}")


async def promises(context: Context) -> Step:
    """Every scenario's own timeline keeps the temporal promises (trust before action, nothing after close, every unit home)."""
    import os

    from brain.baseline import MODELS
    from brain.mind.specs import SPECS, verify_log
    from brain.scenario import DEV_SECRETS, inproc_partners, load_scenario, run_scenario

    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    broken = []
    for sid in context.suite:
        result = await run_scenario(load_scenario(sid), inproc_partners(), models=MODELS, speed=0, timeout_s=30)
        broken += [f"{sid} {v.spec}: {v.message}" for v in verify_log(result.sink.events)]
    return Step("Temporal promises", not broken, f"{len(SPECS)} specifications hold on {len(context.suite)} scenarios" if not broken else "; ".join(broken[:3]))


async def held_out(context: Context) -> Step:
    """Variants of the scenarios, shifted in time, with other noise and a decoy sensor, decide as their base does."""
    from brain.variants import HELD_OUT_SEEDS, check

    ids = ["d2", "d3", "d4"] if context.quick else context.suite
    rows = await check(ids, list(HELD_OUT_SEEDS)[:1])
    wrong = [r for r in rows if not r["passed"]]
    return Step("Held-out variants", not wrong, f"{len(rows)} of {len(rows)} variants decide as their base scenario" if not wrong
                else f"{len(wrong)} differ: " + "; ".join(f"{r['scenario']} {r['transform']} seed {r['seed']}" for r in wrong[:3]))


async def forward_bench_step(context: Context) -> Step:
    """On synthetic streams with a known truth: no spike is ever adopted, a walked threshold still reports the spike, recovery is not doubted."""
    from brain.mind.forward_bench import score

    scores = score(Policy().forward, range(1000, 1003))
    checks = {
        "no spike is adopted": scores["spike"]["spike_adopted"] == 0,
        "a lone spike is reported": scores["spike"]["spike_reported"] == 1,
        "a spike after a walked threshold is reported": scores["walk"]["walk_spike_reported"] == 1,
        "a step is accepted": all(scores[name]["delay"] is not None for name in ("step_s", "step_m", "step_l")),
        "a recovery is not doubted": scores["step_back"]["recovery_false_doubts"] == 0,
    }
    bad = [name for name, ok in checks.items() if not ok]
    return Step("Forward-model benchmark", not bad, "synthetic streams behave as designed" if not bad else f"did not hold: {'; '.join(bad)}", {"scores": scores})


async def team_under_faults(context: Context) -> Step:
    """With half of the role calls failing, the team's fallbacks and the verifier still leave a safe, gate-checked run."""
    from brain.reliability import summary, trials

    rows = await trials("d3", 4 if context.quick else 8, rate=0.5, seed=11)
    report = summary(rows)
    ok = report["passed"] == report["trials"] and report["fallbacks"] + report["rejected"] > 0
    return Step("Team under faults", ok, f"{report['passed']} of {report['trials']} trials passed with half the role calls failing "
                f"({report['fallbacks']} fallbacks, {report['same_decisions']} decided as the scripted team)")


async def offline_step(context: Context) -> Step:
    return Step("Offline", not context.blocked, "no connection left this machine" if not context.blocked
                else f"{len(context.blocked)} attempted: {', '.join(context.blocked[:3])}")


STEPS: list[Callable[[Context], Awaitable[Step]]] = [run_test_book, baselines, promises, held_out, forward_bench_step, team_under_faults, curve, ablations, poison, offline_step]


def screens_step(out: Path, stamp: str) -> Step:
    """The strips and the canopy on d3, and the canopy smoke test, if Chromium is here. Skipped (and passing) if it is not."""
    if not (shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")):
        return Step("Screens", True, "skipped: no Chromium on this machine")
    root = config.home()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = subprocess.Popen(["uv", "run", "brain", "serve", "--port", str(port)], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)  # nosec B310: our own server on loopback
                break
            except OSError:
                time.sleep(0.5)
        else:
            return Step("Screens", False, "the Brain's screen server did not start")
        made = []
        for view in ("strip", "canopy"):
            prefix = out / f"{stamp}-{view}"
            run = subprocess.run(
                ["uv", "run", "python", "scripts/screenshot.py", "1920x1080", str(prefix), f"goto:http://127.0.0.1:{port}/?view={view}&quality=light", "wait:2",
                 "js:document.querySelector('[data-id=d3]').click()", "wait:16", "shot:d3"], cwd=root, capture_output=True, text=True, check=False)
            if "page errors: none" not in run.stdout:
                return Step("Screens", False, f"{view} view raised page errors: {run.stdout[-300:]}")
            made.append(f"{prefix.name}-d3.png")
        smoke = subprocess.run([sys.executable, "scripts/canopy_smoke.py", str(port)], cwd=root, capture_output=True, text=True, check=False)
        if smoke.returncode != 0:
            return Step("Screens", False, f"canopy smoke test failed: {smoke.stdout[-300:]}")
        return Step("Screens", True, f"saved {', '.join(made)}; canopy drew every event type without error")
    finally:
        server.terminate()
        server.wait(timeout=10)


def _markdown(report: Report, quick: bool) -> str:
    lines = [f"# Rehearsal, {report.started[:10]}", "",
             f"Run {report.started} on {platform.node()} ({platform.platform()}), Python {platform.python_version()}, "
             f"{'quick' if quick else 'full'} suite, offline. **{'PASS' if report.passed else 'FAIL'}** in {report.seconds:.0f} s.", "",
             "| step | result | detail |", "|---|---|---|"]
    lines += [f"| {s.name} | {'PASS' if s.passed else 'FAIL'} | {s.detail} |" for s in report.steps]
    for s in report.steps:
        if "table" in s.data:
            lines += ["", "## Ablations", "", s.data["table"]]
        if "rows" in s.data:
            lines += ["", "## Learning curve (d3)", "", "| run | team runs | learned plans used | time to last action (ms) | same decisions as run 1 |", "|---|---|---|---|---|"]
            lines += [f"| {r['run']} | {r['team_runs']} | {r['compiled_plans']} | {r['last_action_ms']} | {'yes' if r['decisions_equal_to_run_1'] else 'NO'} |" for r in s.data["rows"]]
    return "\n".join(lines) + "\n"


async def rehearse(out: Path, quick: bool = False, screens: bool = True) -> Report:
    """Run every step, write `<date>.md` and `<date>.json` into `out`, and return the report."""
    started = datetime.now(UTC)
    clock = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    context = Context(quick=quick, workdir=Path(tempfile.mkdtemp(prefix="rehearsal-")), suite=QUICK_SUITE if quick else DEFAULT_SUITE)
    steps: list[Step] = []
    with offline(context.blocked):
        for run in STEPS:
            try:
                steps.append(await run(context))
            except Exception as error:  # a step that cannot even run has failed; the rest still tell the team what holds  # noqa: BLE001
                steps.append(Step(getattr(run, "__name__", "step"), False, f"{type(error).__name__}: {error}"))
    if screens:
        steps.append(screens_step(out, started.strftime("%Y-%m-%d")))
    report = Report(started.isoformat(timespec="seconds"), steps, time.monotonic() - clock)
    stem = started.strftime("%Y-%m-%d")
    (out / f"{stem}.md").write_text(_markdown(report, quick))
    (out / f"{stem}.json").write_text(json.dumps({"started": report.started, "passed": report.passed, "seconds": round(report.seconds, 1),
                                                 "steps": [{"name": s.name, "passed": s.passed, "detail": s.detail} for s in steps]}, indent=2) + "\n")
    shutil.rmtree(context.workdir, ignore_errors=True)
    return report
