"""MOCK Guardian layer (stand-in, no real detection logic), with an operator console.

Receives signed readings from the Twin, runs only the contract-level checks from the data dictionary
(version, HMAC provenance, sequence_no monotonicity), issues a verdict, and serves the verified readings
to City Brain. An operator (the console at /) can overrule it, marking a sensor untrusted, and can act
as the real Guardian would: quarantine or isolate a sensor, and clear it, through the Twin's actuators.
It deliberately shares no code with the Twin: it is a black box behind HTTP.
"""
from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

CONTRACT_VERSION = "2026-09-17"
HMAC_KEY = os.environ.get("TWIN_HMAC_KEY", "dev-only-hmac-key")
LOG_DIR = os.environ.get("LOG_DIR", "")
TWIN_URL = os.environ.get("TWIN_URL", "http://localhost:8001").rstrip("/")
TWIN_API_KEY = os.environ.get("TWIN_GUARDIAN_API_KEY", "")
UI_DIR = Path(os.environ.get("MOCK_UI_DIR", Path(__file__).parent / "ui"))
DEVICE_ACTUATOR_ID = "device-control-01"
DEVICE_ACTIONS = ("quarantine_device", "isolate_sensor", "clear_quarantine")
PERIODIC_TYPES = {"traffic_camera", "water_level", "rainfall"}  # judged like the others, but too frequent for the timeline
REQUIRED = ("contract_version", "sensor_id", "type", "zone_id", "timestamp", "sequence_no", "value", "provenance")

app = FastAPI(title="Mock Guardian")
_events: deque[dict[str, Any]] = deque(maxlen=1000)
_verdicts: deque[dict[str, Any]] = deque(maxlen=200)
_latest: dict[str, dict[str, Any]] = {}  # sensor_id -> {"reading", "verdict"}
_history: list[dict[str, Any]] = []      # every trusted reading, in order: {"index", "reading", "verdict"}
HISTORY_MAX = 5000
_last_seq: dict[str, int] = {}
_ids = itertools.count(1)
_pending = {"count": 0, "last_flush": 0.0, "untrusted": 0}
_recent: deque[dict[str, Any]] = deque(maxlen=200)  # every reading with its verdict, newest last: the console's stream
_sensors: dict[str, dict[str, Any]] = {}             # sensor_id -> what the console shows about it
_overruled: dict[str, str] = {}                      # sensor_id -> why an operator marked it untrusted


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _emit(kind: str, message: str, **data: Any) -> None:
    event = {"ts": _now(), "layer": "guardian", "kind": kind, "message": message, "data": data}
    _events.append(event)
    if LOG_DIR:
        Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
        with (Path(LOG_DIR) / "guardian.ndjson").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")


def _canonical(reading: dict[str, Any]) -> bytes:
    body = {k: v for k, v in reading.items() if k != "provenance"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _check(reading: dict[str, Any]) -> list[str]:
    reasons = [f"missing field '{f}'" for f in REQUIRED if f not in reading]
    if reasons:
        return reasons
    if reading["contract_version"] != CONTRACT_VERSION:
        reasons.append(f"contract_version mismatch ({reading['contract_version']} != {CONTRACT_VERSION})")
    given = (reading["provenance"] or {}).get("hmac", "")
    expected = hmac.new(HMAC_KEY.encode(), _canonical(reading), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(given, expected):
        reasons.append("HMAC mismatch (payload altered or wrong key)")
    last = _last_seq.get(reading["sensor_id"])
    if last is not None and reading["sequence_no"] <= last:
        reasons.append(f"sequence_no not increasing ({reading['sequence_no']} <= {last}): replay or reorder")
    return reasons


@app.get("/health")
def health():
    return {"status": "ok", "mock": True}


@app.post("/ingest")
async def ingest(request: Request):
    try:
        reading = await request.json()
    except Exception:
        raise HTTPException(400, "body must be a JSON object")
    if not isinstance(reading, dict):
        raise HTTPException(400, "body must be a JSON object")
    reasons = _check(reading)
    sensor_id = reading.get("sensor_id")
    if sensor_id in _overruled:
        reasons.append(f"marked untrusted by the operator: {_overruled[sensor_id]}")
    trusted = not reasons
    verdict = {"verdict_id": f"verdict-{next(_ids):05d}", "trust": "trusted" if trusted else "untrusted", "reasons": reasons,
               "sensor_id": reading.get("sensor_id"), "sequence_no": reading.get("sequence_no"), "at": _now()}
    _verdicts.append(verdict)
    _recent.append({"reading": reading, "verdict": verdict})
    if sensor_id:
        _sensors[sensor_id] = {"sensor_id": sensor_id, "type": reading.get("type"), "zone_id": reading.get("zone_id"),
                               "sequence_no": reading.get("sequence_no"), "last_seen": verdict["at"], "trust": verdict["trust"]}
    if reading.get("type") not in PERIODIC_TYPES:
        _emit("verdict_issued", f"{verdict['verdict_id']} {verdict['trust']} for {reading.get('type')} {sensor_id}",
              verdict_id=verdict["verdict_id"], trust=verdict["trust"], sensor_id=sensor_id)
    if trusted:
        _last_seq[reading["sensor_id"]] = reading["sequence_no"]
        _latest[reading["sensor_id"]] = {"reading": reading, "verdict": verdict}
        index = (_history[-1]["index"] + 1) if _history else 1
        _history.append({"index": index, "reading": reading, "verdict": verdict})
        del _history[:-HISTORY_MAX]
    else:
        _emit("reading_untrusted", f"UNTRUSTED reading from {reading.get('sensor_id')}: {'; '.join(reasons)}", **verdict)
    # throttle the timeline: one summary event per second instead of one per zone reading
    _pending["count"] += 1
    _pending["untrusted"] += 0 if trusted else 1
    if time.monotonic() - _pending["last_flush"] >= 1.0:
        _emit("readings_verified", f"verified {_pending['count']} Twin readings ({_pending['untrusted']} untrusted)", count=_pending["count"])
        _pending.update(count=0, untrusted=0, last_flush=time.monotonic())
    return verdict


@app.get("/verified/readings")
def verified_readings(after: int = 0, types: str = "", limit: int = 500):
    """Trusted readings in arrival order, each with the verdict that vouches for it, from index
    `after` on (a cursor: pass back `next`). `types`: comma-separated reading types to keep.
    What City Brain reads to learn about incidents (every call, not only a sensor's latest)."""
    wanted = {t for t in types.split(",") if t}
    items = [h for h in _history if h["index"] > after and (not wanted or h["reading"]["type"] in wanted)][:limit]
    nxt = items[-1]["index"] if items else max(after, _history[-1]["index"] if _history else 0)
    return {"contract_version": CONTRACT_VERSION, "next": nxt, "items": items}


@app.get("/verdicts")
def verdicts(limit: int = 50):
    return {"verdicts": list(_verdicts)[-limit:]}


@app.get("/events")
def events(limit: int = 200):
    return {"events": list(_events)[-limit:]}


# ---- the operator console's API ---------------------------------------------------------------


@app.get("/api/identity")
def identity():
    return {"layer": "guardian", "twin_url": TWIN_URL}


@app.get("/api/readings")
def recent_readings(limit: int = 50):
    """The stream from the Twin, newest first, with each verdict."""
    return {"items": list(_recent)[-limit:][::-1]}


async def _twin_quarantined(client: httpx.AsyncClient) -> dict[str, str]:
    try:
        devices = (await client.get(f"{TWIN_URL}/quarantine")).json()["devices"]
        return {d["device_id"]: d["mode"] for d in devices}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {}


@app.get("/api/sensors")
async def sensors():
    """Every sensor seen, with its last verdict, whether an operator overruled it, whether the Twin has cut it off."""
    async with httpx.AsyncClient(timeout=2.0) as client:
        quarantined = await _twin_quarantined(client)
    rows = [{**s, "overruled": _overruled.get(s["sensor_id"]), "cut_off": quarantined.get(s["sensor_id"])} for s in _sensors.values()]
    return {"sensors": sorted(rows, key=lambda r: r["sensor_id"])}


class TrustRequest(BaseModel):
    trust: bool
    reason: str = "operator decision"


@app.post("/api/sensors/{sensor_id}/trust")
def set_trust(sensor_id: str, req: TrustRequest):
    """Overrule the checks: from now on the sensor's readings are untrusted, or judged normally again."""
    if req.trust:
        _overruled.pop(sensor_id, None)
        _emit("sensor_trust_restored", f"operator: {sensor_id} is judged normally again", sensor_id=sensor_id)
    else:
        _overruled[sensor_id] = req.reason
        _emit("sensor_marked_untrusted", f"operator: {sensor_id} untrusted, {req.reason}", sensor_id=sensor_id, reason=req.reason)
    return {"sensor_id": sensor_id, "overruled": _overruled.get(sensor_id)}


class DeviceRequest(BaseModel):
    action: str
    reason: str = Field(default="operator decision", min_length=1)


@app.post("/api/sensors/{sensor_id}/actions")
async def device_action(sensor_id: str, req: DeviceRequest):
    """A containment action, sent to the Twin as the Guardian's own actuator call (no trust_ref needed)."""
    if req.action not in DEVICE_ACTIONS:
        raise HTTPException(422, f"unknown action {req.action!r}; one of {list(DEVICE_ACTIONS)}")
    params = {"device_id": sensor_id} if req.action == "clear_quarantine" else {"device_id": sensor_id, "reason": req.reason}
    call = {"contract_version": CONTRACT_VERSION, "actuator_id": DEVICE_ACTUATOR_ID, "action": req.action, "params": params,
            "requesting_layer": "guardian", "justification": f"operator: {req.reason}", "trust_ref": None}
    headers = {"X-Api-Key": TWIN_API_KEY} if TWIN_API_KEY else {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(f"{TWIN_URL}/actuators/call", json=call, headers=headers)
        except httpx.HTTPError as exc:
            _emit("actuator_failed", f"could not reach the Twin: {exc}")
            raise HTTPException(502, f"cannot reach the Twin's actuators: {exc}")
    if resp.status_code >= 400:
        _emit("actuator_failed", f"the Twin refused {req.action} ({resp.status_code}): {resp.text[:200]}")
        raise HTTPException(resp.status_code, resp.json().get("detail", resp.text))
    result = resp.json()["result"]
    _emit("actuator_called", f"{req.action} on {sensor_id}: {result['status']}", action=req.action, result=result)
    return result


if UI_DIR.is_dir():  # last: the API routes above win over the console's files
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="console")
