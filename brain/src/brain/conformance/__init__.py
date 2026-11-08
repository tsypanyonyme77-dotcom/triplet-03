"""The conformance kit: does this Twin, Guardian or Brain follow the contract? One command, one verdict, a fix for each failure.

It checks through the same interfaces the Brain uses (an MCP client for a Twin, HTTP for a Guardian and a Brain), so it works for any
partner that speaks the contract. It does not command a Twin's actuators unless asked (`probe`): a real Twin would act on them.
A check is `pass`, `warn` (allowed by the contract's text, worth knowing), `fail` (the contract is broken) or `skip` (not enough given to check).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from mcp import Client
from pydantic import ValidationError

from brain.contracts import CONTRACT_VERSION, PARAM_MODELS, SensorReading, TrustVerdict
from brain.contracts.signing import sign, verify


@dataclass
class Result:
    id: str
    layer: str
    title: str
    status: str  # pass | warn | fail | skip
    detail: str = ""
    fix: str = ""


def summary(results: list[Result]) -> tuple[int, int, int, int]:
    count = lambda s: sum(1 for r in results if r.status == s)  # noqa: E731
    return count("pass"), count("warn"), count("fail"), count("skip")


def _payload(result: Any) -> Any:
    text = result.content[0].text if result.content else "null"
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"status": "error", "reason": text}


# --------------------------------------------------------------------------- the Twin (MCP)


async def run_twin(target: Any, secret: str | None = None, *, brain_secret: str | None = None, probe: bool = False) -> list[Result]:
    """`target` is a URL or an in-process MCP server. `secret` verifies the Twin's signatures; `brain_secret` signs the probe calls."""
    out: list[Result] = []
    async with Client(target) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        missing = sorted({"list_readings", "get_topology"} - set(tools))
        if missing:
            out.append(Result("T1", "twin", "offers list_readings and get_topology", "fail", f"missing tool(s): {', '.join(missing)}",
                              "expose both as MCP tools (INTERFACE.md, What the Brain receives)"))
            return out + [Result(i, "twin", t, "skip", "needs T1") for i, t in _TWIN_TITLES.items() if i != "T1"]
        out.append(Result("T1", "twin", _TWIN_TITLES["T1"], "pass", f"{len(tools)} tools"))

        if "admin_load_scenario" in tools:  # a stand-in that must be told to start streaming; a real Twin just streams
            from brain.scenario import load_scenario

            scenario = load_scenario("t14")
            await client.call_tool("admin_load_scenario", {"scenario": {k: scenario[k] for k in ("id", "topology", "events", "on_dispatch") if k in scenario}, "speed": 0})
        readings: list[dict[str, Any]] = []
        cursor, shape_problem, advanced = 0, "", True
        for _ in range(12):
            page = _payload(await client.call_tool("list_readings", {"cursor": cursor, "limit": 200}))
            if not isinstance(page, dict) or not isinstance(page.get("readings"), list) or not isinstance(page.get("next_cursor"), int):
                shape_problem = f"expected {{readings: [...], next_cursor: int}}, got {str(page)[:120]}"
                break
            advanced = advanced and page["next_cursor"] >= cursor
            readings += page["readings"]
            if page["readings"]:
                cursor = page["next_cursor"]
                if len(readings) >= 20:
                    break
            elif readings:
                break  # the stream has paused: judge what it has sent
            else:
                await asyncio.sleep(0.25)
        if shape_problem or not advanced:
            out.append(Result("T2", "twin", _TWIN_TITLES["T2"], "fail", shape_problem or "next_cursor went backwards", "return {readings, next_cursor, stream_id?} and advance the cursor"))
        elif not readings:
            out.append(Result("T2", "twin", _TWIN_TITLES["T2"], "warn", "no readings in 3 s: start a scenario on the Twin and run again"))
        else:
            out.append(Result("T2", "twin", _TWIN_TITLES["T2"], "pass", f"{len(readings)} readings, cursor to {cursor}"))

        bad = []
        for reading in readings:
            try:
                SensorReading.model_validate(reading)
            except ValidationError as error:
                bad.append(f"{reading.get('sensor_id')}#{reading.get('sequence_no')}: {error.errors()[0]['loc']} {error.errors()[0]['msg']}")
        out.append(Result("T3", "twin", _TWIN_TITLES["T3"], "fail" if bad else ("pass" if readings else "skip"), bad[0] if bad else f"{len(readings)} valid",
                          "match the envelope in contracts/schemas/SensorReading.schema.json" if bad else ""))

        if not secret:
            out.append(Result("T4", "twin", _TWIN_TITLES["T4"], "skip", "no shared secret given (--twin-secret-env)"))
        else:
            unsigned = [r for r in readings if not verify(r, secret)]
            out.append(Result("T4", "twin", _TWIN_TITLES["T4"], "fail" if unsigned else ("pass" if readings else "skip"),
                              f"{len(unsigned)} of {len(readings)} readings fail HMAC-SHA256 over canonical JSON" if unsigned else f"{len(readings)} verified",
                              "sign canonical JSON (sorted keys, no whitespace, without provenance) with the shared secret" if unsigned else ""))

        last: dict[str, int] = {}
        repeat = ""
        for reading in readings:
            sensor, number = reading.get("sensor_id"), reading.get("sequence_no", 0)
            if sensor in last and number <= last[sensor]:
                repeat = f"{sensor}: {last[sensor]} then {number}"
                break
            last[sensor] = number
        out.append(Result("T5", "twin", _TWIN_TITLES["T5"], "fail" if repeat else ("pass" if readings else "skip"), repeat or "increasing for every sensor",
                          "make sequence_no increase for each sensor" if repeat else ""))

        topology = _payload(await client.call_tool("get_topology", {}))
        needed = {"zones", "adjacency", "exits", "facilities", "sensors"}
        absent = sorted(needed - set(topology)) if isinstance(topology, dict) else sorted(needed)
        zone_ids = {z["id"] if isinstance(z, dict) else z for z in topology.get("zones", [])} if isinstance(topology, dict) else set()
        stray = [s["id"] for s in topology.get("sensors", []) if s.get("zone_id") not in zone_ids] if isinstance(topology, dict) and not absent else []
        problem = f"missing: {', '.join(absent)}" if absent else (f"sensor(s) in an unknown zone: {', '.join(stray[:3])}" if stray else "")
        out.append(Result("T6", "twin", _TWIN_TITLES["T6"], "fail" if problem else "pass", problem or f"{len(zone_ids)} zones", "return zones, adjacency, exits, facilities and sensors, every sensor in a listed zone" if problem else ""))

        listed = sorted(n for n in tools if n in PARAM_MODELS)
        no_call = [n for n in listed if "call" not in (tools[n].input_schema or {}).get("properties", {})]
        out.append(Result("T7", "twin", _TWIN_TITLES["T7"], "fail" if no_call else ("pass" if listed else "warn"),
                          f"{', '.join(no_call)} take no `call` argument" if no_call else (f"{', '.join(listed)}" if listed else "no actuator tools: the Brain can sense but not act"),
                          "each actuator tool takes call=<ActuatorCall envelope>" if no_call else ""))

        if not probe:
            out += [Result(i, "twin", _TWIN_TITLES[i], "skip", "not run: commands the Twin's actuators; pass --probe-actuators on a test Twin") for i in ("T8", "T9")]
            return out
        out += await _probe(client, tools, topology if isinstance(topology, dict) else {}, brain_secret)
    return out


async def _probe(client: Client, tools: dict[str, Any], topology: dict[str, Any], brain_secret: str | None) -> list[Result]:
    station = next((f for f in topology.get("facilities", []) if f.get("type") == "police_station" and f.get("actuator_id")), None)
    if station is None or "dispatch_unit" not in tools:
        return [Result(i, "twin", _TWIN_TITLES[i], "skip", "no police station or no dispatch_unit tool to probe") for i in ("T8", "T9")]

    def envelope(incident: str) -> dict[str, Any]:
        body = {"contract_version": CONTRACT_VERSION, "actuator_id": station["actuator_id"], "action": "dispatch_unit",
                "params": {"unit_type": "police", "zone_id": station["zone_id"], "incident_id": incident, "mode": "respond"},
                "requesting_layer": "city_brain", "justification": "conformance probe", "trust_ref": "verdict-probe"}
        return sign(body, brain_secret, "city_brain") if brain_secret else body

    first = _payload(await client.call_tool("dispatch_unit", {"call": envelope("inc-probe-1")}))
    second = _payload(await client.call_tool("dispatch_unit", {"call": envelope("inc-probe-1")}))
    if first.get("status") != "dispatched":
        t8 = Result("T8", "twin", _TWIN_TITLES["T8"], "warn", f"the probe dispatch was {first.get('status')}: {first.get('reason', '')}", "check --brain-secret-env and the probe station")
    elif second.get("status") == "duplicate" and second.get("unit_id") == first.get("unit_id"):
        t8 = Result("T8", "twin", _TWIN_TITLES["T8"], "pass", f"the repeat answered duplicate for {first['unit_id']}")
    else:
        t8 = Result("T8", "twin", _TWIN_TITLES["T8"], "fail", f"the repeat answered {second.get('status')} unit {second.get('unit_id')}, not duplicate of {first.get('unit_id')}",
                    "a repeated incident, unit type, mode and target must answer {status: duplicate, unit_id: <the unit already sent>}")
    if "recall_unit" not in tools or first.get("status") != "dispatched":
        return [t8, Result("T9", "twin", _TWIN_TITLES["T9"], "warn", "no recall_unit tool: optional, the Brain then only updates its own count")]
    recall = {"contract_version": CONTRACT_VERSION, "actuator_id": station["actuator_id"], "action": "recall_unit", "params": {"unit_id": first["unit_id"], "incident_id": "inc-probe-1"},
              "requesting_layer": "city_brain", "justification": "conformance probe", "trust_ref": "verdict-probe"}
    recalled = _payload(await client.call_tool("recall_unit", {"call": sign(recall, brain_secret, "city_brain") if brain_secret else recall}))
    again = _payload(await client.call_tool("dispatch_unit", {"call": envelope("inc-probe-1")}))
    ok = recalled.get("status") in ("recalled", "duplicate") and again.get("status") == "dispatched" and again.get("unit_id") != first.get("unit_id")
    return [t8, Result("T9", "twin", _TWIN_TITLES["T9"], "pass" if ok else "warn", "a recall frees the place" if ok else f"after the recall a repeat answered {again.get('status')}",
                       "" if ok else "after recall_unit, a new dispatch to the same zone should be a new unit")]


_TWIN_TITLES = {
    "T1": "offers list_readings and get_topology", "T2": "list_readings returns {readings, next_cursor} and the cursor advances",
    "T3": "every reading validates against SensorReading", "T4": "every reading's HMAC verifies with the shared secret",
    "T5": "sequence_no increases per sensor", "T6": "get_topology has zones, adjacency, exits, facilities and sensors in listed zones",
    "T7": "actuator tools take call=<envelope>", "T8": "a repeated dispatch answers duplicate with the same unit_id",
    "T9": "a recalled unit frees its place",
}


# --------------------------------------------------------------------------- the Guardian (REST)


async def run_guardian(client: httpx.AsyncClient, secret: str | None = None, *, deadline_s: float = 2.0) -> list[Result]:
    def reading(sequence: int = 1) -> dict[str, Any]:
        body = {"contract_version": CONTRACT_VERSION, "sensor_id": "kit-cam-01", "type": "traffic_camera", "zone_id": "zone-01",
                "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"), "sequence_no": sequence,
                "value": {"congestion_score": 0.3, "vehicle_count": 12, "avg_speed_kmh": 42.0, "smoke_detected": False}}
        return sign(body, secret, "twin") if secret else body

    async def judge(r: dict[str, Any]) -> tuple[dict[str, Any] | None, float, str]:
        started = time.monotonic()
        try:
            response = await client.post("/verdicts", json={"reading": r})
        except httpx.HTTPError as error:
            return None, 0.0, f"{type(error).__name__}: {error}"
        took = time.monotonic() - started
        return (response.json() if response.status_code == 200 else None), took, "" if response.status_code == 200 else f"HTTP {response.status_code}"

    out: list[Result] = []
    good, took, problem = await judge(reading())
    verdict, why = None, problem
    if good is not None:
        try:
            verdict = TrustVerdict.model_validate(good)
        except ValidationError as error:
            why = f"{error.errors()[0]['loc']}: {error.errors()[0]['msg']}"
    if verdict is None:
        out.append(Result("G1", "guardian", _GUARDIAN_TITLES["G1"], "fail", why or "no verdict", "POST /verdicts {reading} must answer a TrustVerdict (contracts/schemas/TrustVerdict.schema.json)"))
        return out + [Result(i, "guardian", t, "skip", "needs G1") for i, t in _GUARDIAN_TITLES.items() if i != "G1"]
    out.append(Result("G1", "guardian", _GUARDIAN_TITLES["G1"], "pass" if verdict.status.value == "trusted" else "warn", f"{verdict.status.value}, confidence {verdict.confidence}",
                      "" if verdict.status.value == "trusted" else "a well-formed signed reading is usually trusted: check your thresholds"))

    if not secret:
        out.append(Result("G2", "guardian", _GUARDIAN_TITLES["G2"], "skip", "no shared secret given (--twin-secret-env)"))
    else:
        tampered = reading(2)
        tampered["value"] = {**tampered["value"], "vehicle_count": 9999}  # changed after signing
        bad, _, _ = await judge(tampered)
        unsigned = {k: v for k, v in reading(3).items() if k != "provenance"}
        none, _, _ = await judge(unsigned)
        trusted = [name for name, v in (("a tampered reading", bad), ("an unsigned reading", none)) if v and v.get("status") == "trusted"]
        replay, _, _ = await judge(reading(1))
        replayed = bool(replay and replay.get("status") == "trusted")
        if trusted:
            out.append(Result("G2", "guardian", _GUARDIAN_TITLES["G2"], "fail", f"trusted {' and '.join(trusted)}", "check the HMAC and answer untrusted when it does not match"))
        else:
            out.append(Result("G2", "guardian", _GUARDIAN_TITLES["G2"], "warn" if replayed else "pass",
                              "refuses tampered and unsigned readings; a replayed sequence_no was trusted again (the Brain checks replay itself)" if replayed else "refuses tampered, unsigned and replayed readings",
                              "the Data Dictionary asks the Guardian to check sequence_no monotonicity too" if replayed else ""))

    try:
        quarantine = await client.get("/quarantine/kit-device")
        body = quarantine.json() if quarantine.status_code == 200 else {}
        ok = isinstance(body.get("quarantined"), bool)
        out.append(Result("G3", "guardian", _GUARDIAN_TITLES["G3"], "pass" if ok else "fail", f"quarantined={body.get('quarantined')}" if ok else f"HTTP {quarantine.status_code} {str(body)[:80]}",
                          "" if ok else "GET /quarantine/{device_id} answers {device_id, quarantined: bool}"))
    except httpx.HTTPError as error:
        out.append(Result("G3", "guardian", _GUARDIAN_TITLES["G3"], "fail", str(error), "serve GET /quarantine/{device_id}"))
    out.append(Result("G4", "guardian", _GUARDIAN_TITLES["G4"], "pass" if took <= deadline_s else "fail", f"{took * 1000:.0f} ms against {deadline_s * 1000:.0f} ms",
                      "" if took <= deadline_s else "answer within the Brain's verdict_deadline_ms or raise it in config/partners.yaml"))
    out.append(Result("G5", "guardian", _GUARDIAN_TITLES["G5"], "pass" if verdict.expires_at > verdict.issued_at else "fail", f"valid {(verdict.expires_at - verdict.issued_at).total_seconds():.0f} s",
                      "" if verdict.expires_at > verdict.issued_at else "expires_at must be after issued_at"))
    return out


_GUARDIAN_TITLES = {
    "G1": "POST /verdicts answers a valid TrustVerdict", "G2": "a tampered or unsigned reading is not trusted", "G3": "GET /quarantine/{id} answers {device_id, quarantined}",
    "G4": "the verdict arrives within the deadline", "G5": "expires_at is after issued_at",
}


# --------------------------------------------------------------------------- the Brain (HTTP)


async def run_brain(client: httpx.AsyncClient, headers: dict[str, str] | None = None) -> list[Result]:
    headers = headers or {}
    out: list[Result] = []

    async def attempt(id_: str, title: str, fn: Any) -> None:
        try:
            status, detail, fix = await fn()
        except Exception as error:  # a check that cannot run is a failure to report, not a crash of the kit  # noqa: BLE001
            status, detail, fix = "fail", f"{type(error).__name__}: {error}", ""
        out.append(Result(id_, "brain", title, status, detail, fix))

    async def b1():
        r = await client.get("/events", params={"once": True}, headers=headers)
        return ("pass", "text/event-stream", "") if r.status_code == 200 and "text/event-stream" in r.headers.get("content-type", "") else ("fail", f"HTTP {r.status_code}", "serve GET /events as server-sent events")

    async def b2():
        r = await client.post("/api/events", headers=headers, json={"specversion": "1.0", "type": "twin.kit.probe", "source": "city-brain", "data": {}})
        return ("pass", f"refused with {r.status_code}", "") if r.status_code in (403, 422) else ("fail", f"answered {r.status_code}", "a partner must not be able to speak as the Brain")

    async def b3():
        r = await client.post("/api/events", headers=headers, json={"specversion": "1.0", "type": "brain.action.result", "source": "twin", "data": {}})
        return ("pass", f"refused with {r.status_code}", "") if r.status_code in (401, 403, 422) else ("fail", f"answered {r.status_code}", "brain.* events are the Brain's alone")

    async def b4():
        r = await client.get("/schemas")
        names = r.json() if r.status_code == 200 else {}
        listed = str(names)
        return ("pass", "SensorReading and ActuatorCall listed", "") if "SensorReading" in listed and "ActuatorCall" in listed else ("fail", listed[:80], "serve every contract schema at /schemas")

    async def b5():
        r = await client.get("/.well-known/agent-card.json")
        body = r.json() if r.status_code == 200 else {}
        return ("pass", f"{len(body.get('skills', []))} skills", "") if body.get("skills") is not None and body.get("contract_version") else ("fail", f"HTTP {r.status_code}", "serve the agent card")

    async def b6():
        r = await client.get("/.well-known/agent-card.json")
        endpoint = (r.json().get("endpoints") or {}).get("mcp") if r.status_code == 200 else None
        return ("pass", endpoint, "") if endpoint else ("warn", "the card names no MCP endpoint", "enable the Brain's MCP server (mcp.enabled)")

    for id_, title, fn in (("B1", "GET /events streams server-sent events", b1), ("B2", "a pushed event cannot claim source city-brain", b2),
                           ("B3", "a pushed brain.* event is refused", b3), ("B4", "/schemas lists the contract schemas", b4),
                           ("B5", "the agent card is served", b5), ("B6", "the card names an MCP endpoint", b6)):
        await attempt(id_, title, fn)
    return out


# --------------------------------------------------------------------------- reporting


def markdown(date: str, results: list[Result]) -> str:
    passed, warned, failed, skipped = summary(results)
    lines = [f"# Conformance report, {date}", "", f"{passed} passed, {warned} warnings, {failed} failed, {skipped} skipped.", "",
             "| Check | Layer | What | Result | Detail | What to change |", "| --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {r.id} | {r.layer} | {r.title} | {r.status.upper()} | {r.detail} | {r.fix} |" for r in results]
    return "\n".join(lines) + "\n"


def table(results: list[Result]) -> str:
    marks = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "skip": "skip"}
    rows = [f"  {marks[r.status]}  {r.id:3} {r.title}" + (f"  ({r.detail})" if r.detail and r.status != "pass" else "") + (f"\n        fix: {r.fix}" if r.fix and r.status in ("fail", "warn") else "") for r in results]
    passed, warned, failed, skipped = summary(results)
    return "\n".join(rows) + f"\n\n{passed} passed, {warned} warnings, {failed} failed, {skipped} skipped"


def as_json(results: list[Result]) -> str:
    return json.dumps([asdict(r) for r in results], indent=2)
