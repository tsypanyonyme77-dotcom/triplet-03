"""The Guardian team's contract 1.0 (guardian/INTERFACE.md), behind the same two ports as every other partner.

Two classes, because that Guardian does two jobs for the Brain:

* `GuardianV1Adapter` (`GuardianPort`): asks for the verdict on a reading (`POST /v1/verdicts/request`, by sensor and sequence number: the Twin
  pushes the reading itself), checks the verdict's HMAC, and turns it into our `TrustVerdict`; asks `GET /v1/containment` whether a device is
  quarantined; and sends an actuator call through `POST /v1/actuator-calls`, which audits it and checks its effect before it reaches the Twin.
* `GuardianGateway` (`TwinPort`): the Twin as the Brain's gate sees it. Readings, topology and capabilities come from the real Twin; the four
  actions the Guardian audits (valve, grid, signal, dispatch) go through the Guardian; the two it does not know (broadcast, recall) go to the Twin.

What changes in the Brain: nothing but `guardian.adapter: v1` in the config. Names are translated here, not in the Brain.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from typing import Any

import httpx
from pydantic import ValidationError

from brain.contracts import ActuatorCall, ActuatorResult, TrustVerdict
from brain.ports import GuardianUnavailable, TwinError

STATUS = {"trusted": "trusted", "suspect": "suspicious", "untrusted": "untrusted"}  # "unknown" is no verdict: see get_verdict


def canonical(body: dict[str, Any]) -> bytes:
    """Their canonical form (INTERFACE.md section 3): sorted keys, no whitespace, UTF-8."""
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(body: dict[str, Any], secret: str) -> str:
    return hmac.new(secret.encode(), canonical(body), hashlib.sha256).hexdigest()


def to_verdict(raw: dict[str, Any]) -> TrustVerdict:
    """Their verdict in our model: `ts` is `issued_at`, `trust_score` is `confidence`, `suspect` is `suspicious`. The rest (layers, threat level,
    the action they took) stays on the verdict as extra fields, where the explanations and the screen can read it."""
    status = STATUS.get(raw.get("status", ""))
    if status is None:
        raise ValueError(f"unknown verdict status {raw.get('status')!r}")
    return TrustVerdict.model_validate({**raw, "status": status, "confidence": raw.get("trust_score", 0.0), "issued_at": raw["ts"]})


GATEWAY_ACTIONS = {"set_valve_state", "set_grid_connection", "set_signal_phase", "dispatch_unit"}


def to_guardian_call(call: ActuatorCall, dispatcher_id: str | None = None) -> dict[str, Any]:
    """Our actuator call in theirs. Their names: `set_grid_state` and `set_signal` (state + duration_s); the unit's type, mode and target ride in `params`.
    Their registry knows one dispatcher (`dispatch-central`), ours one per station: with `dispatcher_id` set, every dispatch goes to it and names its station in `params`."""
    p = call.params
    if call.action == "set_valve_state":
        action, params = "set_valve_state", {"state": p["state"], **({"flow_target_pct": p["flow_target_pct"]} if p.get("flow_target_pct") is not None else {})}
    elif call.action == "set_grid_connection":
        action, params = "set_grid_state", {"state": p["state"]}
    elif call.action == "set_signal_phase":
        action, params = "set_signal", {"state": p["phase"], "duration_s": p["duration_s"]}
    elif call.action == "dispatch_unit":
        action, params = "dispatch_unit", {"unit_type": p["unit_type"], **{k: p[k] for k in ("mode", "target_id") if p.get(k)}}
        if dispatcher_id:
            params["station_id"] = call.actuator_id
    else:
        raise ValueError(f"the Guardian does not audit {call.action!r}")
    body: dict[str, Any] = {
        "call_id": "call-" + hashlib.sha256(canonical({"a": call.actuator_id, "n": call.action, "p": p, "t": call.trust_ref, "i": str(call.issued_at), "x": call.nonce})).hexdigest()[:12],
        "actuator_id": dispatcher_id if (dispatcher_id and action == "dispatch_unit") else call.actuator_id, "action": action, "params": params, "requesting_layer": "brain",
        "trust_ref": call.trust_ref, "justification": call.justification,
    }
    for key in ("zone_id", "incident_id"):
        if p.get(key):
            body[key] = p[key]
    return body


def from_guardian_answer(call: ActuatorCall, answer: dict[str, Any]) -> ActuatorResult:
    """`forwarded` with an ok Twin reply is a success; anything else is a refusal that keeps the Guardian's reasons."""
    reasons = [str(r) for r in answer.get("reasons", [])]
    if answer.get("decision") != "forwarded":
        return ActuatorResult(status="rejected", reason=", ".join(reasons) or "blocked by the Guardian", guardian=answer)
    reply = answer.get("twin_reply") or {}
    if reply.get("status") != "ok":
        return ActuatorResult(status="rejected", reason=f"twin_rejected: {reply.get('status', 'no reply')}", guardian=answer)
    state = reply.get("current_state") or {}
    extra = {"current_state": state, "reverts_at": reply.get("reverts_at"), "warnings": reasons, "guardian_call_id": answer.get("call_id")}
    if call.action == "dispatch_unit" and (unit := reply.get("unit_id") or state.get("unit_id")):
        extra["unit_id"] = unit
    return ActuatorResult(status="dispatched" if call.action == "dispatch_unit" else "set", **extra)


class GuardianV1Adapter:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None, *, api_key: str | None = None,
                 hmac_secret: str | None = None, dispatcher_id: str | None = None, poll_s: float = 0.1) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url)
        self._headers = {"X-API-Key": api_key} if api_key else {}
        self._secret, self._poll_s, self._dispatcher = hmac_secret, poll_s, dispatcher_id

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_verdict(self, reading: dict[str, Any], deadline_s: float) -> TrustVerdict:
        """The Twin pushes readings to the Guardian, so ours may not have arrived yet: `unknown` is asked again until the deadline, then it is no verdict."""
        end, last = time.monotonic() + deadline_s, "no answer"
        body = {"sensor_id": reading["sensor_id"], "sequence_no": reading["sequence_no"]}
        while True:
            try:
                response = await self._client.post("/v1/verdicts/request", json=body, headers=self._headers, timeout=max(end - time.monotonic(), 0.05))
                response.raise_for_status()
                raw = response.json()
                if raw.get("status") != "unknown":
                    if self._secret is not None and not hmac.compare_digest(sign({k: v for k, v in raw.items() if k != "signature"}, self._secret), str(raw.get("signature"))):
                        raise GuardianUnavailable("the verdict's signature does not match: not trusted")
                    return to_verdict(raw)
                last = f"unknown ({', '.join(map(str, raw.get('reasons', [])))})"
            except httpx.HTTPError as error:
                raise GuardianUnavailable(f"{type(error).__name__}: {error}") from error
            except (ValidationError, ValueError, KeyError) as error:
                raise GuardianUnavailable(f"guardian sent an invalid verdict: {error}") from error
            if time.monotonic() + self._poll_s >= end:
                raise GuardianUnavailable(f"no verdict for {body['sensor_id']}#{body['sequence_no']}: {last}")
            await asyncio.sleep(self._poll_s)

    async def is_quarantined(self, device_id: str) -> bool:
        try:
            response = await self._client.get("/v1/containment", headers=self._headers, timeout=2.0)
            response.raise_for_status()
            return any(entry.get("device_id") == device_id for entry in response.json()["active"])
        except (httpx.HTTPError, KeyError, ValueError) as error:
            raise GuardianUnavailable(f"{type(error).__name__}: {error}") from error

    async def call_actuator(self, call: ActuatorCall) -> ActuatorResult:
        body = to_guardian_call(call, self._dispatcher)
        try:
            response = await self._client.post("/v1/actuator-calls", json=body, headers=self._headers, timeout=15.0)
            response.raise_for_status()
            return from_guardian_answer(call, response.json())
        except (httpx.HTTPError, ValueError) as error:
            raise TwinError(f"guardian gateway: {type(error).__name__}: {error}") from error


class GuardianGateway:
    """The Twin as the gate sees it: audited actions go through the Guardian, everything else to the real Twin."""

    def __init__(self, twin: Any, guardian: GuardianV1Adapter) -> None:
        self._twin, self._guardian = twin, guardian

    async def call_actuator(self, call: ActuatorCall) -> ActuatorResult:
        if call.action in GATEWAY_ACTIONS:
            return await self._guardian.call_actuator(call)
        return await self._twin.call_actuator(call)

    def __getattr__(self, name: str) -> Any:  # stream_readings, get_topology, list_capabilities, close: the Twin's
        return getattr(self._twin, name)
