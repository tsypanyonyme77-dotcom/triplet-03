"""T16 against the real Guardian: a quarantined device is refused, and the Brain's own v1 adapter sees it.

    BRAIN_API_KEY=... OPS_API_KEY=... GUARDIAN_HMAC_KEY=... GUARDIAN_URL=http://localhost:8100 \
        uv run python scripts/live_guardian_t16.py

Needs the Guardian (and its Twin mock) running (`make demo` or `docker compose up` in guardian/). Quarantines `valve-port-12` with the ops key, then checks through
`GuardianV1Adapter` that (1) `is_quarantined` is true, (2) a valve call carrying a trusted verdict is refused with `device_quarantined`,
(3) after the release the device is no longer quarantined. Writes `logs/t16-live-guardian-<ts>.log` (JSON lines) in the repository root; exit 0 = all checks passed.
"""

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from brain.adapters.guardian_v1 import GuardianV1Adapter
from brain.contracts import ActuatorCall

URL, DEVICE = os.environ.get("GUARDIAN_URL", "http://localhost:8100"), "valve-port-12"
LOGS = Path(__file__).resolve().parents[2] / "logs"


async def main() -> int:
    lines: list[dict] = []

    def log(step: str, **data) -> None:
        lines.append({"ts": datetime.now(UTC).isoformat(), "scenario": "T16", "step": step, **data})
        print(json.dumps(lines[-1], default=str))

    ops = {"X-API-Key": os.environ["OPS_API_KEY"]}
    async with httpx.AsyncClient(base_url=URL, timeout=15) as http:
        adapter = GuardianV1Adapter(URL, http, api_key=os.environ["BRAIN_API_KEY"], hmac_secret=os.environ.get("GUARDIAN_HMAC_KEY"))
        latest = (await http.get("/v1/readings/wl-port-03/latest", headers={"X-API-Key": os.environ["BRAIN_API_KEY"]})).json()  # the Twin pushes; ask for what arrived
        verdict = await adapter.get_verdict({"sensor_id": "wl-port-03", "sequence_no": latest["sequence_no"]}, 5.0)
        log("verdict", status=verdict.status, verdict_id=verdict.verdict_id)

        def call() -> ActuatorCall:
            return ActuatorCall(actuator_id=DEVICE, action="set_valve_state", params={"state": "closed", "zone_id": "zone-07"}, trust_ref=verdict.verdict_id, justification="T16 live")

        await http.post("/v1/containment/quarantine", headers=ops, json={"device_id": DEVICE, "device_type": "actuator", "reason": "T16", "zone_id": "zone-07"})
        checks = {"quarantined": await adapter.is_quarantined(DEVICE)}
        refused = await adapter.call_actuator(call())
        log("call while quarantined", status=refused.status, reason=refused.reason)
        checks["call refused: device_quarantined"] = refused.status == "rejected" and "device_quarantined" in (refused.reason or "")
        await http.post("/v1/containment/clear", headers=ops, json={"device_id": DEVICE, "reason": "T16 done"})
        checks["released"] = not await adapter.is_quarantined(DEVICE)
        for what, passed in checks.items():
            log("check", what=what, passed=passed)
        ok = all(checks.values())
        log("end", passed=ok)
    LOGS.mkdir(exist_ok=True)
    (LOGS / f"t16-live-guardian-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}.log").write_text("".join(json.dumps(x, default=str) + "\n" for x in lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
