"""Regenerates tests/fixtures/*.json with the example keys documented in INTERFACE.md.
Run: python -m tests.fixtures.make_fixtures (then paste into INTERFACE.md; test_interface_card checks they match)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from guardian.adapters.schemas import AlertOut, AuditEventOut, DecisionOut, VerdictOut
from guardian.models import Alert, AuditEvent, Decision, LayerResult, Status, ThreatLevel, Verdict
from guardian.trust.signer import Signer
from mocks.common.signing import sign_envelope

EXAMPLE_TWIN_KEY = "example-twin-key"
EXAMPLE_GUARDIAN_KEY = "example-guardian-key"
HERE = Path(__file__).parent


def build() -> dict[str, dict[str, object]]:
    envelope = sign_envelope({
        "contract_version": "1.0", "sensor_id": "wl-port-03", "sensor_type": "water_level", "zone_id": "zone-07",
        "timestamp": "2026-11-02T14:03:18Z", "sequence_no": 4821, "value": {"level_m": 1.80},
        "sequence_reset": False}, EXAMPLE_TWIN_KEY)
    ts = datetime(2026, 11, 2, 14, 3, 23, tzinfo=UTC)
    v = Verdict(
        verdict_id="verdict-88213", sensor_id="wl-port-03", sequence_no=4821, status=Status.untrusted,
        trust_score=0.2, reasons=["rate_of_change", "no_rainfall_corroboration", "no_flow_corroboration"],
        layer_results=[
            LayerResult(layer="L1_authenticity", passed=True, detail="schema, contract_version and HMAC valid"),
            LayerResult(layer="L2_freshness", passed=True, detail="sequence and timestamp fresh"),
            LayerResult(layer="L4_dynamics", passed=False, severity="medium", reason_code="rate_of_change",
                        detail="level_m changed 0.4→1.8 in 5s (0.28/s > 0.01/s)"),
            LayerResult(layer="L5_corroboration", passed=False, severity="strong",
                        reason_code="no_rainfall_corroboration",
                        detail="0 agree / 6 disagree of 6 independent sources"),
            LayerResult(layer="L5_corroboration", passed=False, severity="strong",
                        reason_code="no_flow_corroboration", detail="0 agree / 6 disagree of 6 independent sources"),
        ],
        action_taken="isolate_sensor", threat_level=ThreatLevel.normal, ts=ts, expires_at=ts + timedelta(seconds=30))
    wire = VerdictOut.from_verdict(v).model_dump()
    wire["signature"] = Signer(EXAMPLE_GUARDIAN_KEY).sign(wire, exclude="signature")
    call = {"call_id": "call-551", "actuator_id": "valve-port-12", "action": "set_valve_state",
            "params": {"state": "closed"}, "zone_id": "zone-07", "requesting_layer": "brain",
            "trust_ref": "verdict-88190", "justification": "flood risk zone-07", "incident_id": "inc-77"}
    reply = {"status": "ok", "current_state": {"state": "closed"}, "reverts_at": None}
    decision = DecisionOut.from_decision(Decision(call_id="call-551", decision="forwarded", reasons=[],
                                                  twin_reply=reply)).model_dump()
    alert = AlertOut.from_alert(Alert(
        alert_id="alert-3f9a1c", type="coordinated_spoofing", zone_id="zone-08",
        evidence=[{"signal": "reading_failed", "ts": "2026-11-02T14:05:02Z", "zone_id": "zone-08",
                   "device_id": "wl-res-01", "source": "wl-res-01", "verdict_id": "verdict-9a01",
                   "reasons": ["rate_of_change", "no_rainfall_corroboration"]}],
        suggested_response="zone under attack: act only on readings corroborated by 2+ sources",
        threat_level=ThreatLevel.under_attack, ts=ts)).model_dump()
    event = AuditEventOut.from_event(AuditEvent(
        event_id="evt-5d2e7a90b1c3", ts=ts, type="verdict", scenario_id="T1", sensor_id="wl-port-03",
        zone_id="zone-07", summary="untrusted wl-port-03#4821 score=0.2 [rate_of_change, no_rainfall_corroboration]",
        data={"kind": "verdict", "verdict_id": "verdict-88213", "status": "untrusted", "trust_score": 0.2,
              "reasons": ["rate_of_change", "no_rainfall_corroboration"], "action_taken": "isolate_sensor",
              "threat_level": "normal"})).model_dump()
    error = {"error": "contract_version_mismatch",
             "message": "contract_version '2.0' is not supported; this Guardian speaks '1.0'",
             "field": "contract_version"}
    return {"envelope": envelope, "verdict": wire, "actuator_call": call, "twin_reply": reply,
            "decision": decision, "alert": alert, "timeline_event": event, "error": error}


if __name__ == "__main__":
    for name, body in build().items():
        (HERE / f"{name}.json").write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
        print(name)
