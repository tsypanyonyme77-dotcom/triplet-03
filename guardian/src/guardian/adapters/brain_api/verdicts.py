"""Reading intake (REST push) and verdict endpoints: request, fetch by id, latest usable value, sensor status."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from guardian.adapters.brain_api.deps import error, fail, guardian_of, require_caller
from guardian.adapters.schemas import ErrorOut, VerdictOut, VerdictRequest
from guardian.clock import iso
from guardian.containment.rollback import latest_usable
from guardian.ingest.validator import IngestError

router = APIRouter(prefix="/v1", tags=["verdicts"])
MAX_BATCH = 1000


@router.post("/readings", responses={422: {"model": ErrorOut}, 400: {"model": ErrorOut}})
async def post_readings(request: Request, caller: str = Depends(require_caller)) -> Any:
    """Push one envelope or a list of envelopes. Returns one verdict (or error) per reading, in order."""
    g = guardian_of(request)
    try:
        body = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return error(400, "schema_invalid", "body is not valid JSON")
    single = isinstance(body, dict)
    items = [body] if single else body
    if not isinstance(items, list):
        return error(400, "schema_invalid", "body must be a reading object or a list of readings")
    if len(items) > MAX_BATCH:
        return error(413, "batch_too_large", f"at most {MAX_BATCH} readings per request")
    results = await g.pipeline.ingest_many(items, source=caller)
    if single and isinstance(results[0], IngestError):
        e = results[0]
        return error(422, e.code, e.message, e.field)
    out = [{"error": r.as_dict()} if isinstance(r, IngestError)
           else {"verdict": VerdictOut.from_verdict(r).model_dump()} for r in results]
    return JSONResponse({"results": out})


@router.post("/verdicts/request", response_model=VerdictOut)
async def request_verdict(req: VerdictRequest, request: Request, _: str = Depends(require_caller)) -> VerdictOut:
    """Verdict for the latest (or a given) reading. Unknown sensor, stale data or any error → `unknown`."""
    v = guardian_of(request).pipeline.request_verdict(req.sensor_id, req.sequence_no)
    return VerdictOut.from_verdict(v)


@router.get("/verdicts/{verdict_id}", response_model=VerdictOut, responses={404: {"model": ErrorOut}})
async def get_verdict(verdict_id: str, request: Request, _: str = Depends(require_caller)) -> VerdictOut:
    v = guardian_of(request).state.get_verdict(verdict_id)
    if v is None:
        raise fail(404, "verdict_not_found", f"no verdict {verdict_id}", "verdict_id")
    return VerdictOut.from_verdict(v)


@router.get("/readings/{sensor_id}/latest", responses={404: {"model": ErrorOut}})
async def latest(sensor_id: str, request: Request, _: str = Depends(require_caller)) -> dict[str, Any]:
    """Latest usable value; when the sensor is contained or its latest reading untrusted, the last-known-good
    value with `rolled_back: true`."""
    g = guardian_of(request)
    s = g.state.get(sensor_id)
    if s is None:
        raise fail(404, "sensor_not_found", f"unknown sensor {sensor_id}", "sensor_id")
    return latest_usable(s, g.containment.contained_reason(sensor_id), g.liveness.is_stale(s))


@router.get("/sensors/{sensor_id}/status", responses={404: {"model": ErrorOut}})
async def sensor_status(sensor_id: str, request: Request, _: str = Depends(require_caller)) -> dict[str, Any]:
    g = guardian_of(request)
    s = g.state.get(sensor_id)
    if s is None:
        raise fail(404, "sensor_not_found", f"unknown sensor {sensor_id}", "sensor_id")
    v = s.latest_verdict
    return {
        "sensor_id": sensor_id, "sensor_type": s.sensor_type, "zone_id": s.zone_id,
        "trust_state": v.status.value if v else "unknown",
        "isolated": g.containment.is_isolated(sensor_id), "quarantined": g.containment.is_quarantined(sensor_id),
        "stale": g.liveness.is_stale(s), "last_seen": iso(s.last_seen) if s.last_seen else None,
        "last_sequence_no": s.last_seq, "flagged": sensor_id in g.correlator.flagged_sources,
        "baseline_frozen": sensor_id in g.baseline.frozen,
        "last_verdict": VerdictOut.from_verdict(v).model_dump() if v else None,
    }
