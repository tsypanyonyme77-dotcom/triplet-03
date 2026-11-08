"""The City Brain's actuator calls (its contract 2026-09-17), whichever carrier brings them (HTTP or MCP).

Authentication: `provenance.hmac` is HMAC-SHA256 over the call without `provenance` and `trust`, keys sorted,
no whitespace, UTF-8, with the secret in BRAIN_HMAC_SECRET. The City Brain signs whole-number floats as
integers (6.0 as 6) and still accepts the older form, so both are checked. A valid X-Api-Key
(TWIN_BRAIN_API_KEY) also authenticates. With neither configured, calls are not authenticated (tests).
Freshness: a call stamped (`issued_at`) more than CLOCK_SKEW_S from now is refused, and its `nonce` is
the idempotency key, so a call sent twice runs once and the second gets the first answer.

Translation into our calls: a dispatch addressed to a station's facility id (`dispatch-hospital`) sends
a unit of that station; the partner's incident id is linked to our incident (incident_links). Other
actions are addressed as `<action>-<zone>` by the City Brain (`broadcast-alert-zone-03`), which names our
actuator for that action. The answer is the actuator's result, flat, as the City Brain reads it.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

from twin.actuation import Actuation, CallRefused
from twin.actuators import ACTUATORS
from twin.city.base import CitySource
from twin.contract import ActuatorCall
from twin.events import EventLog
from twin.partners import partner_dispatch
from twin.partners.incident_links import IncidentLinks
from twin.partners.topology import station_of

UNSIGNED_FIELDS = ("provenance", "trust")
CLOCK_SKEW_S = 30.0
# what the City Brain may call here: the actuators that do something in this city and that it is allowed to use
OFFERED = ("dispatch_unit", "recall_unit", "broadcast_alert", "set_pump_state", "set_barrier_state")


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _whole(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer() and abs(value) < 2**53:
        return int(value)
    if isinstance(value, dict):
        return {k: _whole(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_whole(v) for v in value]
    return value


def brain_signature(envelope: dict[str, Any], secret: str) -> str:
    """The signature the City Brain puts on an envelope (its current form: whole-number floats as integers)."""
    signed = {k: v for k, v in envelope.items() if k not in UNSIGNED_FIELDS}
    return hmac.new(secret.encode(), _canonical(_whole(signed)), hashlib.sha256).hexdigest()


def signature_ok(envelope: dict[str, Any], secret: str) -> bool:
    given = (envelope.get("provenance") or {}).get("hmac")
    if not isinstance(given, str):
        return False
    signed = {k: v for k, v in envelope.items() if k not in UNSIGNED_FIELDS}
    forms = (_canonical(_whole(signed)), _canonical(signed))
    return any(hmac.compare_digest(given, hmac.new(secret.encode(), form, hashlib.sha256).hexdigest()) for form in forms)


def capabilities() -> dict[str, str]:
    """{action: description} of what the City Brain can call here."""
    return {action: ACTUATORS[action]["description"] for action in OFFERED}


class BrainDoor:
    def __init__(self, actuation: Actuation, city: CitySource, links: IncidentLinks, events: EventLog, *,
                 hmac_secret: str = "", api_key: str = "", clock_skew_s: float = CLOCK_SKEW_S) -> None:
        self.actuation, self.city, self.links, self.events = actuation, city, links, events
        self.hmac_secret, self.api_key, self.clock_skew_s = hmac_secret, api_key, clock_skew_s

    # ---- who is calling ------------------------------------------------------------------

    def authenticate(self, raw: dict[str, Any], api_key: str | None = None) -> None:
        if not self.hmac_secret and not self.api_key:
            return
        if self.api_key and api_key == self.api_key:
            return
        if self.hmac_secret and (raw.get("provenance") or {}).get("signed_by") == "city_brain" and signature_ok(raw, self.hmac_secret):
            self._check_fresh(raw)
            return
        raise self.actuation.refuse(401, "missing or invalid signature: provenance.hmac must be the City Brain's HMAC-SHA256 of the "
                                         "call (or send a valid X-Api-Key)", "unauthorized", "city brain call rejected: bad signature")

    def _check_fresh(self, raw: dict[str, Any]) -> None:
        issued = raw.get("issued_at")
        if issued is None:
            return
        try:
            when = datetime.fromisoformat(str(issued).replace("Z", "+00:00"))
        except ValueError:
            raise CallRefused(422, f"issued_at {issued!r} is not an ISO-8601 time") from None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if abs((datetime.now(timezone.utc) - when).total_seconds()) > self.clock_skew_s:
            raise self.actuation.refuse(401, f"issued_at {issued} is more than {self.clock_skew_s:.0f} s from now", "stale_call",
                                        "city brain call rejected: issued_at too far from now")

    # ---- the call --------------------------------------------------------------------------

    def handle(self, action: str, raw: Any, api_key: str | None = None) -> dict[str, Any]:
        """Authenticate, translate, run. Returns the flat result; raises CallRefused for a call that must not run."""
        if not isinstance(raw, dict):
            raise CallRefused(422, "the call must be a JSON object (the actuator call envelope)")
        self.authenticate(raw, api_key)
        if raw.get("action", action) != action:
            raise CallRefused(400, f"the call's action '{raw.get('action')}' does not match the tool or path '{action}'")
        if action not in OFFERED:
            raise CallRefused(404, f"action '{action}' is not offered by this Twin; offered: {list(OFFERED)} (GET /capabilities)")
        if raw.get("requesting_layer", "city_brain") != "city_brain":
            raise CallRefused(403, "this door is the City Brain's: requesting_layer must be 'city_brain'")
        params = raw.get("params")
        if not isinstance(params, dict):
            raise CallRefused(422, "params must be an object")
        nonce = raw.get("nonce")
        common = {"contract_version": raw.get("contract_version", ""), "action": action, "requesting_layer": "city_brain",
                  "justification": str(raw.get("justification") or "")[:500] or "(none given)", "trust_ref": raw.get("trust_ref"),
                  "idempotency_key": f"brain-nonce:{nonce}"[:128] if nonce else None}
        if action == "dispatch_unit":
            actuator_id = raw.get("actuator_id")
            return partner_dispatch.dispatch(self.actuation, self.city, self.links, self.events, who="city brain",
                                             addressed_to=actuator_id if isinstance(actuator_id, str) else "", params=params,
                                             partner_incident=params.get("incident_id"), common=common)
        self._check_actuator_id(action, raw.get("actuator_id"))
        ours = dict(params)
        if isinstance(ours.get("incident_id"), str):
            ours["incident_id"] = self.links.ours(ours["incident_id"]) or ours["incident_id"]
        return partner_dispatch.run(self.actuation, ActuatorCall(actuator_id=ACTUATORS[action]["actuator_id"], params=ours, **common))

    def _check_actuator_id(self, action: str, actuator_id: Any) -> None:
        ours = ACTUATORS[action]["actuator_id"]
        if action == "recall_unit" and isinstance(actuator_id, str) and station_of(self.city, actuator_id):
            return   # a recall goes to the station the unit came from
        zones = {z["zone_id"] for z in self.city.zones()}
        named = {ours} | {f"{action.replace('_', '-')}-{z}" for z in zones}
        if actuator_id not in named:
            raise CallRefused(400, f"actuator_id '{actuator_id}' is not a {action} actuator here; use '{ours}' or "
                                   f"'{action.replace('_', '-')}-<zone_id>'")
