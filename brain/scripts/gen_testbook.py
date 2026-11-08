"""Writes docs/TESTBOOK-brain.md from the scenario files, in the fields the Phase 1 text asks for.

    uv run python scripts/gen_testbook.py

ID, name, layers involved, description, trigger, expected Twin, expected Guardian, expected Brain, how to verify. Generated, so it cannot
drift from `scenarios/`; a test compares this output with the committed file.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def scenarios() -> list[dict]:
    from brain.scenario import load_raw_scenario  # resolves a scenario that points at another (`same_as`)

    files = sorted((ROOT / "scenarios").glob("t*.json"), key=lambda p: int(p.stem[1:]))
    return [{**load_raw_scenario(p.stem), "topology": None} for p in files]


def twin_line(s: dict) -> str:
    events = s.get("events", [])
    sensors = sorted({e["sensor_id"] for e in events if "sensor_id" in e} | {st["sensor_id"] for st in s.get("streams", []) if "sensor_id" in st})
    kinds = sorted({e["type"] for e in events if "type" in e} | {st["type"] for st in s.get("streams", []) if "type" in st})
    return f"Streams {len(events) or 'its'} signed readings from {len(sensors)} sensor{'s' if len(sensors) != 1 else ''} ({', '.join(kinds)}); answers each actuator call."


def guardian_line(s: dict) -> str:
    guardian = s.get("guardian", {})
    overrides = guardian.get("overrides", {})
    parts = [f"Judges every reading `{guardian.get('default', 'trusted')}` by default, each within the Brain's 2 s verdict deadline"]
    if overrides:
        parts.append("except " + ", ".join(f"{k}: `{v}`" for k, v in overrides.items()))
    if guardian.get("quarantined"):
        parts.append("and reports " + ", ".join(guardian["quarantined"]) + " as quarantined")
    if guardian.get("down") or guardian.get("unavailable"):
        parts.append("and goes silent")
    if "guardian" in s.get("faults", {}):
        parts.append(f"and goes silent after {s['faults']['guardian']['after_verdicts']} verdicts")
    return " ".join(parts) + "."


def sections(level: str = "##") -> list[str]:
    out: list[str] = []
    for n, s in enumerate(scenarios(), 1):
        expect = s.get("expect", {})
        out += [f"{level} {s['id'].upper()}: {s['name']}", "",
                "| Field | |", "| --- | --- |",
                f"| ID | {s['id'].upper()} |", f"| Name | {s['name']} |", f"| Layers involved | {', '.join(s.get('layers', []))} |",
                f"| Description | {s.get('description', '')} |",
                f"| Trigger | `./scenarios/triggers/{s['id']}.sh`, or `uv run brain scenario {s['id']}` |",
                f"| Expected: Twin | {twin_line(s)} |", f"| Expected: Guardian | {guardian_line(s)} |",
                f"| Expected: Brain | {s.get('expected_brain', '')} |",
                f"| How to verify | Timeline screen (key `{n}`); log file `logs/{s['id']}-*.jsonl`; `uv run brain scenario {s['id']} --inproc --speed 0` prints each check; `uv run brain replay logs/canonical/{s['id']}.inputs.jsonl` reproduces it |", ""]
        if expect.get("dispatched") is not None:
            out += [f"Checked: dispatched units {expect['dispatched'] or 'none'}; forbidden events {expect.get('forbidden_events', [])}.", ""]
    return out


COVERAGE = [  # interaction, what it shows, Guardian-team scenarios, Brain scenarios
    ("Twin → Brain", "The city runs normally and the Brain reacts correctly to real events", "", "T12, T14"),
    ("Twin → Guardian", "The Guardian recognizes healthy and unhealthy data", "T1, T2, T3, T4, T7, T8, T9", "T13"),
    ("Brain → Guardian", "Trust verdicts change decisions, and decisions stay safe", "T5, T6, T10", "T13, T14, T16"),
    ("All three", "The whole city works as one system, including when something goes wrong", "T11", "T15"),
]
GUARDIAN = [  # from guardian/README.md ("Test Book scenarios"); full fields are in guardian/tests/scenarios and logs/t*-guardian-*.log
    ("T1", "Fake flood at the port (1.80 m vs 0.40 m, no rain)", "`untrusted` within 10 s, sensor isolated, rollback serves 0.40 m, the Brain does not move the valve"),
    ("T2", "Stuck / dead sensor", "flatline → `suspect`; silence → stale → `unknown`"),
    ("T3", "Replayed readings", "repeated `sequence_no` with valid HMAC → `untrusted` (`replay`); `sequence_reset` accepted"),
    ("T4", "Emergency-call flood", "more than 5 calls/zone/min → `call_flood`, `suspect`, throttled, none dropped; duplicate `call_id` → `untrusted`"),
    ("T5", "Valve closed, no effect", "`actuator_failure` alert (\"use a backup\"); untrusted flow sensor → `unknown` instead"),
    ("T6", "The Brain uses a quarantined device", "call blocked, reason `device_quarantined`"),
    ("T7", "Twin goes silent", "every sensor `unknown`, `/health` degraded"),
    ("T8", "Fire in the open sea", "`untrusted` (`impossible_location`), dispatch blocked"),
    ("T9", "Coordinated spoofing in a zone", "zone `under_attack`, trusted needs ≥ 0.9 and 2 sources, hysteresis back to normal"),
    ("T10", "Command injection without `trust_ref`", "blocked, caller quarantined after 3, `command_injection` alert"),
    ("T11", "Real flood + attack elsewhere", "corroborated flood `trusted`, valve call forwarded and verified, fake alarm `untrusted`"),
]
HEAD = "Generated by `brain/scripts/gen_testbook.py` from `brain/scenarios/`; do not edit by hand. Each Brain scenario is launched by one command (`brain/scenarios/triggers/<id>.sh`, or the number key on the timeline screen) and leaves a log in the root `logs/` folder."


def coverage() -> list[str]:
    return ["| Interaction | What it shows | Guardian-team scenarios | Brain-team scenarios |", "| --- | --- | --- | --- |",
            *[f"| {a} | {b} | {c or '-'} | {d} |" for a, b, c, d in COVERAGE], ""]


def render() -> str:
    return "\n".join(["# Test Book: the City Brain", "", HEAD, "", "## Which scenario covers which interaction", "", *coverage(), *sections()])


def render_root() -> str:
    guardian = ["| ID | Name | Expected Guardian behaviour |", "| --- | --- | --- |", *[f"| {i} | {n} | {b} |" for i, n, b in GUARDIAN], ""]
    return "\n".join([
        "# Test Book", "",
        "Scenarios are ours. Taken together they test all three layers and every interaction between them. One shared numbering: **T1-T11 are the Guardian team's, T12-T16 the Brain team's.** Reliability is checked, not claimed: each scenario has a one-command trigger and a log in `logs/`.", "",
        HEAD, "", "## Coverage", "", *coverage(),
        "## Guardian scenarios (T1-T11)", "",
        "Run against the Guardian's Twin and Brain mocks: `make scenario T=T1` in `guardian/`; logs `logs/t<N>-guardian-*.log`. Each has an in-process test in `guardian/tests/scenarios/`.", "", *guardian,
        "## Brain scenarios (T12-T16)", "",
        "One command each, e.g. `./brain/scenarios/triggers/t14.sh`; logs `logs/t<N>-*.jsonl`. The Guardian in these runs is the Brain's scripted mock (`brain/mocks/guardian`), so a verdict is exactly what the scenario says; the same call paths run against the real Guardian are checked in `brain/docs/GUARDIAN-COMPAT.md`.", "",
        *sections("###"), "Expected outputs are concrete and observable, not \"the system behaves correctly\".", ""])


if __name__ == "__main__":
    (ROOT / "docs" / "TESTBOOK-brain.md").write_text(render())
    (ROOT.parent / "TESTBOOK.md").write_text(render_root())
    print("wrote docs/TESTBOOK-brain.md and ../TESTBOOK.md")
