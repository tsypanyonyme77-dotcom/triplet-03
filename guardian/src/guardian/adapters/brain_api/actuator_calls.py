"""Audited actuator gateway: the Brain's actuator calls go through the call auditor, never straight to the Twin."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from guardian.adapters.brain_api.deps import guardian_of, require_caller
from guardian.adapters.schemas import ActuatorCallIn, DecisionOut, ErrorOut

router = APIRouter(prefix="/v1", tags=["actuators"])


@router.post("/actuator-calls", response_model=DecisionOut, responses={422: {"model": ErrorOut}})
async def actuator_call(call: ActuatorCallIn, request: Request, caller: str = Depends(require_caller)) -> DecisionOut:
    """Returns 200 with `decision: forwarded|blocked` and the reasons; blocked calls never reach the Twin."""
    d = await guardian_of(request).auditor.handle(call.to_call(), caller)
    return DecisionOut.from_decision(d)
