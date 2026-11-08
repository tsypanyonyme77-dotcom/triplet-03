"""Health, threat, alerts, containment and signature-helper endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from guardian.adapters.brain_api.deps import fail, guardian_of, require_caller
from guardian.adapters.schemas import AlertOut, ClearRequest, ErrorOut, QuarantineRequest, VerdictOut
from guardian.adapters.schemas.wire import verdict_payload
from guardian.clock import iso
from guardian.models import ContainmentRecord, LayerResult, Status
from guardian.trust.signer import canonical_json

router = APIRouter(tags=["system"])


def _rec(r: ContainmentRecord) -> dict[str, Any]:
    return {**r.model_dump(mode="json"), "since": iso(r.since)}


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    return guardian_of(request).health()


@router.get("/v1/threat")
async def threat(request: Request, _: str = Depends(require_caller)) -> dict[str, Any]:
    g = guardian_of(request)
    return {"zones": {z: g.levels.get(z).value for z in g.cfg.city.zones},
            "incidents": g.correlator.open_incidents(), "flagged_sources": sorted(g.correlator.flagged_sources)}


@router.get("/v1/alerts", response_model=list[AlertOut])
async def alerts(request: Request, since: datetime | None = Query(default=None),
                 _: str = Depends(require_caller)) -> list[AlertOut]:
    return [AlertOut.from_alert(a) for a in guardian_of(request).alerts.since(since)]


@router.get("/v1/containment")
async def containment(request: Request, _: str = Depends(require_caller)) -> dict[str, Any]:
    return {"active": [_rec(r) for r in guardian_of(request).containment.active()]}


@router.post("/v1/containment/clear", responses={404: {"model": ErrorOut}})
async def clear(req: ClearRequest, request: Request, caller: str = Depends(require_caller)) -> dict[str, Any]:
    g = guardian_of(request)
    cleared = await g.containment.clear(req.device_id, f"{req.reason} (by {caller})", manual=True)
    if not cleared:
        raise fail(404, "not_contained", f"{req.device_id} is not isolated or quarantined", "device_id")
    return {"cleared": [_rec(r) for r in cleared]}


@router.post("/v1/containment/quarantine", responses={403: {"model": ErrorOut}})
async def quarantine(req: QuarantineRequest, request: Request, caller: str = Depends(require_caller)) -> dict[str, Any]:
    """Operator quarantine (ops key only). Automatic quarantine comes from the threat correlator."""
    if caller != "ops":
        raise fail(403, "forbidden", "manual quarantine needs the ops API key")
    r = await guardian_of(request).containment.quarantine(req.device_id, req.device_type,
                                                          f"{req.reason} (by ops)", req.zone_id)
    return {"quarantined": _rec(r)}


@router.get("/v1/verify/signature")
async def verify_signature(request: Request, verdict_id: str | None = None,
                           _: str = Depends(require_caller)) -> dict[str, Any]:
    """Shows the exact canonical bytes we sign, so partners can test their verifier. Without verdict_id a
    sample verdict is signed on the fly (not stored)."""
    g = guardian_of(request)
    if verdict_id:
        v = g.state.get_verdict(verdict_id)
        if v is None:
            raise fail(404, "verdict_not_found", f"no verdict {verdict_id}", "verdict_id")
    else:
        v = g.engine.sign(g.engine.build(
            sensor_id="sample-sensor", sequence_no=1, status=Status.trusted, score=1.0, reasons=[],
            results=[LayerResult(layer="L1_authenticity", passed=True, detail="sample")]))
    payload = verdict_payload(v)
    return {"verdict": VerdictOut.from_verdict(v).model_dump(), "canonical": canonical_json(payload).decode(),
            "algorithm": "HMAC-SHA256(GUARDIAN_HMAC_KEY, canonical_json(verdict minus signature))",
            "valid": g.engine.verify(v)}
