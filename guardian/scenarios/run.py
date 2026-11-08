"""Scenario CLI (R2): `python -m scenarios.run T1` triggers a Test Book scenario against the running stack
(docker compose up) and writes logs/t5-scenario-T1-<ts>.log. Exit code 0 = expected behaviour observed."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from guardian.clock import SystemClock

GUARDIAN = os.environ.get("GUARDIAN_URL", "http://localhost:8100")
TWIN = os.environ.get("TWIN_URL", "http://localhost:8101")
BRAIN = os.environ.get("BRAIN_URL", "http://localhost:8102")
CLOCK = SystemClock()


class Run:
    def __init__(self, sid: str) -> None:
        self.sid = sid
        self.headers = {"X-API-Key": os.environ.get("BRAIN_API_KEY", ""), "X-Scenario-Id": sid}
        self.ops = {"X-API-Key": os.environ.get("OPS_API_KEY", ""), "X-Scenario-Id": sid}
        self.g = httpx.AsyncClient(base_url=GUARDIAN, timeout=10)
        self.t = httpx.AsyncClient(base_url=TWIN, timeout=10)
        self.b = httpx.AsyncClient(base_url=BRAIN, timeout=10, headers={"X-Scenario-Id": sid})
        self.lines: list[dict[str, Any]] = []
        self.ok = True

    def log(self, step: str, **data: Any) -> None:
        entry = {"ts": datetime.now(UTC).isoformat(), "scenario": self.sid, "step": step, **data}
        self.lines.append(entry)
        print(json.dumps(entry, default=str))

    def expect(self, what: str, cond: bool, **data: Any) -> None:
        self.ok &= cond
        self.log("check", what=what, passed=cond, **data)

    async def inject(self, kind: str, **params: Any) -> None:
        r = await self.t.post(f"/inject/{kind}", json=params)
        self.log("inject", kind=kind, params=params, status=r.status_code)

    async def wait(self, seconds: float) -> None:
        self.log("wait", seconds=seconds)
        await CLOCK.sleep(seconds)

    async def verdict(self, sensor_id: str) -> dict[str, Any]:
        r = await self.g.post("/v1/verdicts/request", json={"sensor_id": sensor_id}, headers=self.headers)
        v = dict(r.json())
        self.log("verdict", sensor_id=sensor_id, status=v.get("status"), reasons=v.get("reasons"))
        return v

    async def get(self, path: str, **kw: Any) -> Any:
        return (await self.g.get(path, headers=self.headers, **kw)).json()

    async def brain_call(self, **call: Any) -> dict[str, Any]:
        d = dict((await self.b.post("/brain/call", json=call)).json())
        self.log("brain_call", call=call, decision=d.get("decision"), reasons=d.get("reasons"))
        return d

    async def clear(self, *devices: str) -> None:
        await self.inject("clear", weather=True)
        for d in devices:
            await self.g.post("/v1/containment/clear", json={"device_id": d, "reason": f"{self.sid} cleanup"},
                              headers=self.ops)

    async def reset(self) -> None:
        """Start from a clean slate: release every containment a previous scenario may have left, and clear twin
        faults. Without this, `run all` is order-dependent — e.g. a sensor isolated earlier makes a later
        scenario's trust_ref untrusted and its actuator call is blocked before any effect check runs."""
        with contextlib.suppress(httpx.HTTPError):
            for rec in (await self.get("/v1/containment")).get("active", []):
                await self.g.post("/v1/containment/clear",
                                  json={"device_id": rec["device_id"], "reason": f"{self.sid} pre-reset"},
                                  headers=self.ops)
        await self.inject("clear", weather=True)

    def alerts_of(self, alerts: list[dict[str, Any]], type_: str) -> list[dict[str, Any]]:
        return [a for a in alerts if a["type"] == type_]


async def t1(r: Run) -> None:
    await r.inject("fake_flood", sensor_id="wl-port-03", level_m=1.80)
    await r.wait(10)
    v = await r.verdict("wl-port-03")
    r.expect("verdict untrusted", v["status"] == "untrusted", reasons=v["reasons"])
    latest = await r.get("/v1/readings/wl-port-03/latest")
    r.expect("rollback to ~0.40 m", bool(latest.get("rolled_back")), value=latest.get("value"))
    d = (await r.b.post("/brain/check-flood", json={"sensor_id": "wl-port-03", "zone_id": "zone-07"})).json()
    r.expect("brain does not touch the valve", d.get("brain") == "ignored", brain=d)
    await r.clear("wl-port-03")


async def t2(r: Run) -> None:
    await r.inject("stuck", sensor_id="wl-port-03", interval_s=1)
    await r.wait(55)
    st = await r.get("/v1/sensors/wl-port-03/status")
    lv = st.get("last_verdict") or {}
    r.expect("flatline -> suspect", lv.get("status") == "suspect" and "flatline" in lv.get("reasons", []), last=lv)
    await r.inject("silence", sensor_id="wl-port-03")
    await r.wait(12)
    v = await r.verdict("wl-port-03")
    r.expect("silent -> unknown", v["status"] == "unknown")
    await r.clear("wl-port-03")


async def t3(r: Run) -> None:
    await r.inject("replay", sensor_id="wl-port-03")
    await r.wait(3)
    alerts = await r.get("/v1/alerts")
    r.expect("replay detected", bool(r.alerts_of(alerts, "replay")))
    await r.inject("sequence_reset", sensor_id="wl-port-03")
    await r.wait(7)
    st = await r.get("/v1/sensors/wl-port-03/status")
    lv = st.get("last_verdict") or {}
    r.expect("sequence reset not a replay", "replay" not in lv.get("reasons", []), seq=st.get("last_sequence_no"))
    await r.clear()


async def t4(r: Run) -> None:
    await r.inject("call_flood", zone_id="zone-08", count=8)
    await r.wait(3)
    alerts = await r.get("/v1/alerts")
    r.expect("call flood detected", bool(r.alerts_of(alerts, "flood_dos")))
    await r.inject("duplicate_call")
    await r.wait(3)
    v = await r.verdict("ec-gw-08")
    r.expect("duplicate call untrusted", "duplicate_call" in v["reasons"], reasons=v["reasons"])


async def t5(r: Run) -> None:
    await r.inject("valve_stuck", actuator_id="valve-port-12")
    v = await r.verdict("wl-port-03")
    d = await r.brain_call(actuator_id="valve-port-12", action="set_valve_state", params={"state": "closed"},
                           zone_id="zone-07", trust_ref=v["verdict_id"], justification="T5 flood risk")
    r.expect("call forwarded", d.get("decision") == "forwarded")
    await r.wait(35)
    alerts = await r.get("/v1/alerts")
    r.expect("actuator_failure alert", bool(r.alerts_of(alerts, "actuator_failure")))
    await r.clear("valve-port-12")
    await r.t.post("/tools/set_valve_state", json={"actuator_id": "valve-port-12", "params": {"state": "open"}})


async def t6(r: Run) -> None:
    await r.g.post("/v1/containment/quarantine", headers=r.ops,
                   json={"device_id": "valve-port-12", "device_type": "actuator", "reason": "T6", "zone_id": "zone-07"})
    v = await r.verdict("wl-port-03")
    d = await r.brain_call(actuator_id="valve-port-12", action="set_valve_state", params={"state": "closed"},
                           zone_id="zone-07", trust_ref=v["verdict_id"], justification="T6")
    r.expect("blocked device_quarantined", "device_quarantined" in d.get("reasons", []))
    await r.clear("valve-port-12")


async def t7(r: Run) -> None:
    await r.inject("silence")
    await r.wait(25)
    h = (await r.g.get("/health")).json()
    r.expect("health degraded", h.get("twin") == "degraded", health=h)
    v = await r.verdict("fm-port-01")
    r.expect("verdict unknown", v["status"] == "unknown")
    await r.clear()


async def t8(r: Run) -> None:
    await r.inject("fire_in_sea")
    await r.wait(3)
    v = await r.verdict("ec-gw-12")
    r.expect("fire in sea untrusted", v["status"] == "untrusted" and "impossible_location" in v["reasons"])
    d = await r.brain_call(actuator_id="dispatch-central", action="dispatch_unit", params={"unit_type": "fire"},
                           zone_id="zone-12", trust_ref=v["verdict_id"], incident_id=f"inc-{r.sid}",
                           justification="T8 fire call")
    r.expect("no dispatch", d.get("decision") == "blocked")


async def t9(r: Run) -> None:
    await r.inject("coordinated", zone_id="zone-08")
    await r.wait(25)
    threat = await r.get("/v1/threat")
    r.expect("zone-08 under_attack", threat["zones"].get("zone-08") == "under_attack", threat=threat["zones"])
    await r.clear("wl-res-01", "aq-res-01", "tc-res-01")


async def t10(r: Run) -> None:
    for i in range(3):
        d = await r.brain_call(actuator_id="grid-port", action="set_grid_state", params={"state": "disconnected"},
                               zone_id="zone-07", trust_ref=None, justification=f"T10 #{i}")
        r.expect(f"call {i} blocked", d.get("decision") == "blocked")
    cont = await r.get("/v1/containment")
    r.expect("brain quarantined", any(c["device_id"] == "brain" for c in cont["active"]))
    r.expect("command_injection alert", bool(r.alerts_of(await r.get("/v1/alerts"), "command_injection")))
    await r.clear("brain")


async def t11(r: Run) -> None:
    await r.inject("real_flood", rainfall_mm_h=40)
    for _ in range(90):  # up to 15 min at TWIN_SPEED=1
        await r.wait(10)
        latest = await r.get("/v1/readings/wl-port-03/latest")
        if (latest.get("value") or {}).get("level_m", 0) > 1.3:
            break
    v = await r.verdict("wl-port-03")
    r.expect("real flood trusted", v["status"] == "trusted", reasons=v["reasons"])
    await r.inject("spike", sensor_id="aq-res-01", value=380.0)
    await r.wait(12)
    alerts = await r.get("/v1/alerts")
    r.expect("attack elsewhere flagged", bool(r.alerts_of(alerts, "attack_during_incident")))
    d = (await r.b.post("/brain/check-flood", json={"sensor_id": "wl-port-03", "zone_id": "zone-07"})).json()
    r.expect("valve call forwarded", d.get("decision") == "forwarded", brain=d)
    await r.clear("aq-res-01")


SCENARIOS: dict[str, Callable[[Run], Awaitable[None]]] = {
    "T1": t1, "T2": t2, "T3": t3, "T4": t4, "T5": t5, "T6": t6, "T7": t7, "T8": t8, "T9": t9, "T10": t10, "T11": t11,
}


async def run(sid: str) -> bool:
    r = Run(sid)
    r.log("start", guardian=GUARDIAN, twin=TWIN, brain=BRAIN)
    try:
        await r.reset()
        await SCENARIOS[sid](r)
    except httpx.HTTPError as e:
        r.expect("stack reachable", False, error=str(e))
    r.log("end", passed=r.ok)
    out = Path(os.environ.get("LOG_DIR", "logs"))
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"t5-scenario-{sid}-{datetime.now(UTC):%Y%m%dT%H%M%S}.log"
    path.write_text("".join(json.dumps(x, default=str) + "\n" for x in r.lines))
    print(f"{sid}: {'PASS' if r.ok else 'FAIL'} -> {path}")
    return r.ok


def main(argv: list[str]) -> int:
    ids = list(SCENARIOS) if argv[:1] == ["all"] else [a.upper() for a in argv]
    if not ids or any(i not in SCENARIOS for i in ids):
        print(f"usage: python -m scenarios.run <{'|'.join(SCENARIOS)}|all>")
        return 2
    return 0 if all([asyncio.run(run(i)) for i in ids]) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
