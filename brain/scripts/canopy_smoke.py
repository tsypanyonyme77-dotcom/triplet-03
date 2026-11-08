"""Feed the running screen one event of every type the Brain emits and check the canopy and the strip feed draw without an error,
and that the picker shows the four scenarios and the relay bar is there.

    uv run brain serve --port 8099 &
    uv run python scripts/canopy_smoke.py 8099

The event types come from the code map (`docs/codebase/graph.json`), so a new event type is covered once the map is rebuilt.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE_JS = """(() => { const types = %TYPES%; const t = new Date().toISOString();
const data = { field: "level_m", observed: 2, expected: 1, z: 9, run: 1, type: "flood", zone_id: "zone-01", params: {}, actions: [], recruited: [], bids: [], reasons: {},
  evidence: [], departments: [], citations: [], status: "completed", decision_id: "dec-1", tier: "reflex", action: "broadcast_alert", entity_id: "p-1", level: "poi",
  score: 0.5, features: [], salience: 0.5, holding: [], slots: [], incidents: [], reading_id: "x#1", reason: "r", rule_id: "LRN-1", would_have: "broadcast_alert",
  check: "trust_ref", unit_id: "unit-p-01", state: "en_route", path: [], signals: [], disconnect: [], zones: [], problems: [], playbook: [], concerns: [], bids_list: [], eta_s: 1, gain_s: 1, load_removed_kw: 1, excess_kw: 1 };
const ev = (type, k) => ({ specversion: "1.0", id: type + k, source: "city-brain", type, time: t, subject: "inc-0001", traceid: "x:" + (k % 3), data });
const out = [];
out.push("keys:" + document.querySelectorAll("#keys .key").length, "relay:" + (document.querySelector("#relay") ? "yes" : "no"));
for (const view of ["canopy", "strip"]) { setView(view);
  for (const copies of [1, 2]) { events = types.map(ev); if (copies === 2) events.push(...events.slice()); cursor = events.length;
    try { render(); out.push(view + ":" + copies + ":ok"); } catch (error) { out.push(view + ":" + copies + ":" + error.message); } } }
events = []; cursor = 0; render(); return out.join(" "); })()"""


def main(port: str) -> int:
    graph = json.loads((ROOT / "docs/codebase/graph.json").read_text())
    nodes = graph["nodes"] if "nodes" in graph else graph
    types = sorted({n["id"].split(":", 1)[1] for n in nodes if n.get("kind") == "event"})
    script = PAGE_JS.replace("%TYPES%", json.dumps(types)).replace("\n", " ")
    done = subprocess.run(
        ["uv", "run", "python", "scripts/screenshot.py", "1920x1080", "/tmp/canopy-smoke", f"goto:http://127.0.0.1:{port}/?quality=light", "wait:2", f"js:{script}"],
        cwd=ROOT, capture_output=True, text=True,
    )
    print(done.stdout.strip())
    return 0 if "keys:4 relay:yes canopy:1:ok canopy:2:ok strip:1:ok strip:2:ok" in done.stdout and "page errors: none" in done.stdout else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "8080"))
