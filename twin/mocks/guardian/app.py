"""MOCK Guardian layer (stand-in, no real detection logic), with an operator console. It speaks the real
Guardian's contract 1.0 (guardian/INTERFACE.md), so the Twin alone exercises what it uses with the real one:

  POST /v1/readings          one envelope or a list, `X-API-Key`; answers {"results": [{"verdict": ...} | {"error": ...}]}
  POST /v1/verdicts/request  a verdict by {sensor_id, sequence_no}, as the City Brain asks for it
  containment                sent to the Twin's POST /tools/{action}, as the real Guardian does

It runs only the contract-level checks (version, HMAC, sequence_no). Unlike the real one it takes any sensor type, and
an operator (the console at /) can overrule it, marking a sensor untrusted, or quarantine and clear a sensor.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

CONTRACT_VERSION = "1.0"
VERDICT_TTL_S = 30
HMAC_KEY = os.environ.get("TWIN_HMAC_SECRET") or os.environ.get("TWIN_HMAC_KEY") or "dev-only-hmac-key"
LOG_DIR = os.environ.get("LOG_DIR", "")
TWIN_URL = os.environ.get("TWIN_URL", "http://localhost:8001").rstrip("/")
TWIN_API_KEY = os.environ.get("TWIN_API_KEY", "")      # what the Twin must send us; none set: open (a stand-in)
UI_DIR = Path(os.environ.get("MOCK_UI_DIR", Path(__file__).parent / "ui"))
DEVICE_ACTIONS = ("quarantine_device", "isolate_sensor", "clear_quarantine")
PERIODIC_TYPES = {"traffic_camera", "water_level", "rain_gauge", "flow_meter", "air_quality"}  # judged like the others, but too frequent for the timeline
REQUIRED = ("contract_version", "sensor_id", "sensor_type", "zone_id", "timestamp", "sequence_no", "value", "hmac")

app = FastAPI(title="Mock Guardian")
_events: deque[dict[str, Any]] = deque(maxlen=1000)
_verdicts: deque[dict[str, Any]] = deque(maxlen=200)
_latest: dict[str, dict[str, Any]] = {}  # sensor_id -> {"reading", "verdict"}
_by_reading: dict[tuple[str, int], dict[str, Any]] = {}   # (sensor_id, sequence_no) -> its verdict
_BY_READING_MAX = 20000
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
    body = {k: v for k, v in reading.items() if k != "hmac"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _check(reading: dict[str, Any]) -> list[str]:
    reasons = [f"missing field '{f}'" for f in REQUIRED if f not in reading]
    if reasons:
        return reasons
    if reading["contract_version"] != CONTRACT_VERSION:
        reasons.append(f"contract_version mismatch ({reading['contract_version']} != {CONTRACT_VERSION})")
    given = str(reading["hmac"])
    expected = hmac.new(HMAC_KEY.encode(), _canonical(reading), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(given, expected):
        reasons.append("HMAC mismatch (payload altered or wrong key)")
    last = _last_seq.get(reading["sensor_id"])
    if last is not None and reading["sequence_no"] <= last and not reading.get("sequence_reset"):
        reasons.append(f"sequence_no not increasing ({reading['sequence_no']} <= {last}): replay or reorder")
    return reasons


@app.get("/health")
def health():
    return {"status": "ok", "mock": True}


def _judge(reading: dict[str, Any]) -> dict[str, Any]:
    reasons = _check(reading)
    sensor_id = reading.get("sensor_id")
    if sensor_id in _overruled:
        reasons.append(f"marked untrusted by the operator: {_overruled[sensor_id]}")
    trusted = not reasons
    now = datetime.now(timezone.utc)
    verdict = {"verdict_id": f"verdict-{next(_ids):05d}", "reading_ref": {"sensor_id": sensor_id, "sequence_no": reading.get("sequence_no")},
               "status": "trusted" if trusted else "untrusted", "trust_score": 1.0 if trusted else 0.0, "reasons": reasons, "ts": _now(),
               "expires_at": (now + timedelta(seconds=VERDICT_TTL_S)).isoformat(timespec="milliseconds").replace("+00:00", "Z")}
    kind = reading.get("sensor_type")
    _verdicts.append(verdict)
    _recent.append({"reading": reading, "verdict": verdict})
    if sensor_id:
        _sensors[sensor_id] = {"sensor_id": sensor_id, "type": kind, "zone_id": reading.get("zone_id"),
                               "sequence_no": reading.get("sequence_no"), "last_seen": verdict["ts"], "trust": verdict["status"]}
        _by_reading[(sensor_id, reading.get("sequence_no"))] = verdict
        while len(_by_reading) > _BY_READING_MAX:
            del _by_reading[next(iter(_by_reading))]
    if kind not in PERIODIC_TYPES:
        _emit("verdict_issued", f"{verdict['verdict_id']} {verdict['status']} for {kind} {sensor_id}",
              verdict_id=verdict["verdict_id"], trust=verdict["status"], sensor_id=sensor_id)
    if trusted:
        _last_seq[reading["sensor_id"]] = reading["sequence_no"]
    else:
        _emit("reading_untrusted", f"UNTRUSTED reading from {sensor_id}: {'; '.join(reasons)}", **verdict)
    # throttle the timeline: one summary event per second instead of one per zone reading
    _pending["count"] += 1
    _pending["untrusted"] += 0 if trusted else 1
    if time.monotonic() - _pending["last_flush"] >= 1.0:
        _emit("readings_verified", f"verified {_pending['count']} Twin readings ({_pending['untrusted']} untrusted)", count=_pending["count"])
        _pending.update(count=0, untrusted=0, last_flush=time.monotonic())
    return verdict


@app.post("/v1/readings")
async def readings(request: Request, x_api_key: str | None = Header(default=None)):
    """One envelope or a list, as the real Guardian takes them: a verdict or an error per reading, in order."""
    if TWIN_API_KEY and x_api_key != TWIN_API_KEY:
        raise HTTPException(401, {"error": "auth_required", "message": "missing or invalid X-API-Key"})
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, {"error": "schema_invalid", "message": "body must be JSON"})
    items = body if isinstance(body, list) else [body]
    results: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            results.append({"error": {"error": "schema_invalid", "message": "a reading must be a JSON object"}})
        else:
            results.append({"verdict": _judge(item)})
    return {"results": results}


class VerdictRequest(BaseModel):
    sensor_id: str
    sequence_no: int | None = None


@app.post("/v1/verdicts/request")
def verdict_request(req: VerdictRequest):
    """The verdict on a reading, or on the sensor's latest. A reading not seen yet is `unknown`: asked again, it may have arrived."""
    sequence_no = req.sequence_no if req.sequence_no is not None else _last_seq.get(req.sensor_id)
    found = _by_reading.get((req.sensor_id, sequence_no))
    if found is not None:
        return found
    return {"verdict_id": f"verdict-{next(_ids):05d}", "reading_ref": {"sensor_id": req.sensor_id, "sequence_no": sequence_no}, "status": "unknown",
            "trust_score": 0.0, "reasons": ["no_verdict"], "ts": _now(), "expires_at": _now()}


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
    call = {"call_id": f"gcall-{next(_ids):05d}", "actuator_id": sensor_id, "action": req.action, "params": {"device_id": sensor_id},
            "zone_id": _sensors.get(sensor_id, {}).get("zone_id"), "requesting_layer": "guardian", "trust_ref": None,
            "justification": f"operator: {req.reason}", "incident_id": None}
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.post(f"{TWIN_URL}/tools/{req.action}", json=call)
        except httpx.HTTPError as exc:
            _emit("actuator_failed", f"could not reach the Twin: {exc}")
            raise HTTPException(502, f"cannot reach the Twin's actuators: {exc}")
    if resp.status_code >= 400:
        _emit("actuator_failed", f"the Twin refused {req.action} ({resp.status_code}): {resp.text[:200]}")
        raise HTTPException(resp.status_code, resp.json().get("detail", resp.text))
    reply = resp.json()
    result = reply.get("current_state") or reply
    if reply.get("status") != "ok":
        _emit("actuator_failed", f"the Twin refused {req.action}: {reply.get('reason')}")
        raise HTTPException(409, f"the Twin refused {req.action}: {reply.get('reason')}")
    _emit("actuator_called", f"{req.action} on {sensor_id}: {result.get('status')}", action=req.action, result=result)
    return result


if UI_DIR.is_dir():  # last: the API routes above win over the console's files
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="console")
