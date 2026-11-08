#!/usr/bin/env python3
"""Test support: an accident through the whole chain in one process, no servers and no clock: the engine
as the Twin's city, the Twin's API (actuators through its real HTTP handlers, via a test client), the
mock Guardian and the mock City Brain's incident board. The rule checks can drive it a tick at a time.
Manual mode (default): the Brain lists the incident and waits. auto=True: its auto rule answers.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from fastapi.testclient import TestClient 

from twin.city.two_blocks import TwoBlocksCity 
from twin.config import Settings 
from twin.main import create_app 

KEY, API_KEY = "dev-only-hmac-key", "scenario-key"
READING_EVERY_S = 1.0
REQUIRED_MANUAL = ("incident", "first_report", "verdict")
REQUIRED_AUTO = REQUIRED_MANUAL + ("decision", "unit_dispatched", "unit_arrived")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ChainRun:
    """One scenario run through the whole chain, a tick at a time. Has `.sim` and `.step()`
    like twin.world.scenarios.Scenario, so the engine's rule checks can drive it."""

    def __init__(self, scenario: str, seed: int | None = None, record: bool = True, auto: bool = False) -> None:
        self.name, self.seed, self.record, self.auto = scenario, seed, record, auto
        self.city = TwoBlocksCity(scenario, seed)
        from twin.world.record import frame  # noqa: PLC0415 (engine on sys.path now)
        self._frame = frame
        self.app = create_app(Settings(hmac_key=KEY, brain_api_key=API_KEY, emit_enabled=False), self.city)
        self.twin = TestClient(self.app)
        self.guardian = TestClient(_load(ROOT / "twin" / "mocks" / "guardian" / "app.py", f"mock_guardian_{id(self)}").app)
        self.brain = _load(ROOT / "twin" / "mocks" / "brain" / "incident_rule.py", "mock_brain_rule")
        self.board = self.brain.IncidentBoard()
        self.rule = self.brain.IncidentDispatchRule() if auto else None  # manual mode: nobody decides
        self.emitter, self.sim = self.app.state.emitter, self.city.sim
        self.timeline: list[dict] = []
        self.frames: list[dict] = []
        self._seen_sim = 0
        self._ticks = 0
        self._every = round(READING_EVERY_S / self.city.dt)

    def note(self, t: float, layer: str, kind: str, message: str, **data) -> None:
        self.timeline.append({"t": round(t, 2), "layer": layer, "kind": kind, "message": message, **data})

    def step(self) -> None:
        self.city.step(self.city.dt)
        self._ticks += 1
        sim, t = self.sim, self.sim._sim_time
        for e in sim.timeline[self._seen_sim:]:
            self.note(e["t"], "twin-sim", e["kind"], _describe(e), **{k: v for k, v in e.items() if k not in ("t", "kind")})
        self._seen_sim = len(sim.timeline)
        if self._ticks % self._every == 0:
            self._exchange(t)
        if self.record:
            self.frames.append(self._frame(sim, t))

    def _exchange(self, t: float) -> None:
        """Readings to the Guardian, trusted reports onto the Brain's board, (auto) its calls to the Twin."""
        for reading in self.emitter.build_readings():
            if reading["type"] in ("traffic_camera", "air_quality", "water_level", "rainfall"):
                continue  # periodic feeds: verified too in the real stack, left out of this timeline
            verdict = self.guardian.post("/ingest", json=reading).json()
            v = reading["value"]
            self.note(t, "twin", "reading_emitted", f"{reading['type']} {reading['sensor_id']} seq {reading['sequence_no']} "
                      f"-> {v.get('incident_id')}", sensor_id=reading["sensor_id"], type=reading["type"])
            self.note(t, "guardian", "verdict", f"{verdict['verdict_id']} {verdict['trust']} for {reading['sensor_id']}",
                      verdict_id=verdict["verdict_id"], trust=verdict["trust"])
            noted = self.board.observe(reading, verdict, t)
            if noted:
                wait = f"deciding in {self.rule.decision_delay_s:.0f} s" if self.rule else "listed, waiting for an operator"
                self.note(t, "city_brain", "first_report", f"first trusted report of {noted['incident_id']} "
                          f"({noted['first_type']}), {wait}", incident_id=noted["incident_id"])
                if self.rule:
                    self.rule.notice(noted, t)
        if self.rule:
            for action, call in self.rule.due(self.board, t):
                self.act(action, call, t)

    def act(self, action: str, call: dict, t: float | None = None) -> dict:
        """Sends one City Brain actuator call to the Twin and records it (also for scripted operators)."""
        t = self.sim._sim_time if t is None else t
        p = call["params"]
        self.note(t, "city_brain", "decision", f"{action} on {p['incident_id']} (trust_ref {call['trust_ref']}, "
                  f"key {call['idempotency_key']})", incident_id=p["incident_id"], action=action)
        resp = self.twin.post("/actuators/call", json=call, headers={"X-Api-Key": API_KEY})
        body = resp.json()
        result = body.get("result", body)
        self.board.record_action(p["incident_id"], action, call, resp.status_code, result)
        self.note(t, "twin", "actuator_result", f"{call['action']} {action} -> {result.get('status', resp.status_code)} "
                  f"{result.get('unit_id', result.get('reason', ''))}", http=resp.status_code, **result)
        return result

    def missing(self) -> list[str]:
        kinds = {e["kind"] for e in self.timeline}
        if "fire_started" in kinds:
            kinds.add("incident")  # a fire is the incident of a fire scenario
        missing = [k for k in (REQUIRED_AUTO if self.auto else REQUIRED_MANUAL) if k not in kinds]
        if not self.auto and "unit_pulled_out" in kinds and "decision" not in kinds:
            missing.append("no unit may move without an actuator call")
        return missing

    def finish(self, seconds: float) -> dict:
        """Writes the log (and the recording) and returns what run() returns."""
        from twin.world.record import map_section, recording_path  # noqa: PLC0415
        self.timeline.sort(key=lambda e: e["t"])
        missing = self.missing()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log = ROOT / "logs" / f"{self.name}-chain-{stamp}.log"
        log.parent.mkdir(exist_ok=True)
        mode = "auto" if self.auto else "manual"
        with log.open("w", encoding="utf-8") as fh:
            fh.write(f"# {self.name} incident chain ({mode} City Brain), seed {self.seed}, {seconds:.0f} s sim, written {stamp}\n")
            for e in self.timeline:
                fh.write(f"t={e['t']:7.1f}  {e['layer']:<10} {e['kind']:<22} {e['message']}\n")
            fh.write(f"# result: {'OK' if not missing else 'INCOMPLETE, missing ' + ', '.join(missing)}\n")
        out = None
        if self.record:
            out = recording_path(self.name)
            out.write_text(json.dumps({"dt": self.city.dt, "map": map_section(self.sim), "frames": self.frames},
                                      separators=(",", ":")))
        return {"timeline": self.timeline, "missing": missing, "log": log, "recording": out, "city": self.city,
                "board": self.board}


def run(scenario: str, seconds: float, seed: int | None = None, record: bool = True, auto: bool = False) -> dict:
    chain = ChainRun(scenario, seed, record, auto)
    for _ in range(round(seconds / chain.city.dt)):
        chain.step()
    return chain.finish(seconds)


def _describe(e: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in e.items() if k not in ("t", "kind"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("scenario", nargs="?", default="ped-hit", choices=["ped-hit", "car-crash", "building-fire", "flood"])
    ap.add_argument("--seconds", type=float, default=300.0)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--auto", action="store_true", help="the City Brain dispatches by itself (default: manual, it only lists)")
    args = ap.parse_args()
    result = run(args.scenario, args.seconds, args.seed, auto=args.auto)
    print(f"log: {result['log']}")
    if result["recording"]:
        print(f"recording: {result['recording']} (viewer ?rec={args.scenario})")
    for e in result["timeline"]:
        if e["kind"] not in ("verdict", "reading_emitted"):
            print(f"t={e['t']:7.1f}  {e['layer']:<10} {e['kind']:<22} {e['message'][:110]}")
    print("OK" if not result["missing"] else f"INCOMPLETE: missing {result['missing']}")
    return 0 if not result["missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
