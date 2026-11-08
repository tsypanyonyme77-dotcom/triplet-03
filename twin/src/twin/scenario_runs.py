"""One trigger, one log (R2). A run loads its engine scenario, waits until every incident is closed (or
the time is up), checks the Test Book's expectations against the events of all layers and writes
logs/<id>-<UTC time>.log. The button and the scripts in scenarios/ both end up here."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from twin.contract import now_iso
from twin.events import EventLog
from twin.live import LiveRunner
from twin.testbook import SCENARIOS, TestBookScenario
from twin.timeline import collect, is_routine

log = logging.getLogger("twin.scenario_runs")

POLL_S = 0.25
KEEP_RUNS = 20  # finished runs kept with their whole timeline, newest last
DEFAULT_SPEED = 4.0  # a whole incident in about a minute


class ScenarioBusy(RuntimeError):
    pass


class ScenarioRunner:
    def __init__(self, live: LiveRunner, events: EventLog, partners: dict[str, str], log_dir: str, on_new_run=lambda: None) -> None:
        self.live, self.events, self.partners, self.log_dir = live, events, partners, log_dir
        self.on_new_run = on_new_run
        self.current: dict[str, Any] | None = None
        self.last: dict[str, Any] | None = None
        self.history: list[dict[str, Any]] = []  # finished runs, each with every event of all layers
        self._number = 0
        self._task: asyncio.Task | None = None

    def status(self) -> dict[str, Any]:
        return {"scenarios": [s.as_dict() for s in SCENARIOS.values()], "current": self.current, "last": self.last}

    def start(self, scenario_id: str, seed: int | None = None, speed: float = DEFAULT_SPEED, brain: str = "auto") -> dict[str, Any]:
        scenario = SCENARIOS[scenario_id]
        if self.current is not None:
            raise ScenarioBusy(f"{self.current['id']} is still running")
        self._number += 1
        self.current = {"run": self._number, "id": scenario.id, "name": scenario.name, "started_at": now_iso(), "seed": seed,
                        "speed": speed, "brain": brain}
        self._task = asyncio.create_task(self._run(scenario, seed, speed, brain), name=f"scenario {scenario.id}")
        return self.current

    async def _run(self, scenario: TestBookScenario, seed: int | None, speed: float, brain: str) -> None:
        started, number = self.current["started_at"], self.current["run"]
        try:
            await self._set_brain_mode(brain)
            self.events.emit("scenario_started", f"{scenario.id} {scenario.name} (brain: {brain})", scenario=scenario.id)
            await self.live.control("speed", speed=speed)
            await self.live.control("load", scenario=scenario.engine_scenario, seed=seed)
            self.on_new_run()
            ended = await self._wait_until_closed(scenario)
            report, events = await self._report(scenario, started, ended)
            self.last = {"run": number, "name": scenario.name, "started_at": started, **report}
            self.events.emit("scenario_finished", f"{scenario.id}: {self.last['result']} ({self.last['log']})", **self.last)
        except Exception as exc:  # a failed run must say so and leave the runner usable
            log.exception("scenario %s failed", scenario.id)
            self.last = {"run": number, "id": scenario.id, "name": scenario.name, "started_at": started, "result": "ERROR",
                         "error": repr(exc)[:300], "log": None, "finished_at": now_iso()}
            self.events.emit("scenario_failed", f"{scenario.id} could not finish: {exc}", scenario=scenario.id)
            events = []
        finally:
            self.current = None
        self.history.append({**self.last, "events": events})
        del self.history[:-KEEP_RUNS]

    def runs(self) -> list[dict[str, Any]]:
        """Finished runs, newest first, without their events."""
        return [{k: v for k, v in r.items() if k != "events"} for r in reversed(self.history)]

    def run(self, number: int) -> dict[str, Any] | None:
        """One finished run with every event of all three layers, routine ones flagged."""
        return next((r for r in self.history if r["run"] == number), None)

    async def _set_brain_mode(self, brain: str) -> None:
        """Asks a mock Brain to decide by itself or to wait for its operator. A real Brain has its own
        mind: the call simply fails and nothing changes."""
        url = self.partners.get("city_brain")
        if not url:
            return
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                (await client.post(f"{url}/api/mode", json={"auto": brain == "auto"})).raise_for_status()
        except httpx.HTTPError as exc:
            self.events.emit("brain_mode_unchanged", f"the City Brain decides for itself ({type(exc).__name__})")

    async def _wait_until_closed(self, scenario: TestBookScenario) -> str:
        city = self.live.city
        while city.sim_time < scenario.timeout_sim_s:
            responses = city.responses()
            if responses and all(r["phase"] == "closed" for r in responses):
                return "closed"
            if self.live.engine_error:
                return "engine_error"
            await asyncio.sleep(POLL_S)
        return "timeout"

    async def _report(self, scenario: TestBookScenario, started: str, ended: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """The run's result and log, and every event of it (routine ones flagged) for its timeline."""
        everything = await collect(self.events, self.partners, since=started, limit=20000, routine=True)
        merged = {"layers": everything["layers"], "events": [e for e in everything["events"] if not e["routine"]]}
        seen = {(e["layer"], e["kind"]) for e in merged["events"]}
        checks = [{"layer": e.layer, "kind": e.kind, "meaning": e.meaning, "seen": (e.layer, e.kind) in seen} for e in scenario.expected]
        result = "PASS" if ended == "closed" and all(c["seen"] for c in checks) else "FAIL"
        path = self._write_log(scenario, started, ended, result, merged, checks)
        report = {"id": scenario.id, "result": result, "ended": ended, "log": path, "checks": checks, "layers": merged["layers"],
                  "finished_at": now_iso()}
        return report, everything["events"]

    def _write_log(self, scenario, started, ended, result, merged, checks) -> str | None:
        if not self.log_dir:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = Path(self.log_dir) / f"{scenario.id}-{stamp}.log"
        lines = [f"# {scenario.id} {scenario.name}", f"# started {started}, ended: {ended}, seed {self.live.city.seed}, run {self.live.city.run_id}"]
        lines += [f"# layer {layer}: {'reachable' if s['reachable'] else 'NOT reachable, ' + str(s['error'])}" for layer, s in merged["layers"].items()]
        lines += [f"{e['ts']}  {e['layer']:<10} {e['kind']:<26} {e['message']}" for e in merged["events"]]
        lines += [f"# {'seen   ' if c['seen'] else 'MISSING'} {c['layer']}:{c['kind']} ({c['meaning']})" for c in checks]
        lines.append(f"# result: {result}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path.name
