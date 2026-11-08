"""Writes docs/TESTBOOK-brain.md from the scenario files, in the fields the Phase 1 text asks for.

    uv run python scripts/gen_testbook.py

ID, name, layers involved, description, trigger, expected Twin, expected Guardian, expected Brain, how to verify. Generated, so it cannot
drift from `scenarios/`; a test compares this output with the committed file.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def scenarios() -> list[dict]:
    from brain.scenario import load_raw_scenario  # resolves a scenario that points at another (`same_as`)

    files = sorted((ROOT / "scenarios").glob("d*.json"), key=lambda p: int(p.stem[1:]))
    return [{**load_raw_scenario(p.stem), "topology": None} for p in files]


def twin_line(s: dict) -> str:
    events = s.get("events", [])
    sensors = sorted({e["sensor_id"] for e in events if "sensor_id" in e} | {st["sensor_id"] for st in s.get("streams", []) if "sensor_id" in st})
    kinds = sorted({e["type"] for e in events if "type" in e} | {st["type"] for st in s.get("streams", []) if "type" in st})
    return f"Streams {len(events) or 'its'} signed readings from {len(sensors)} sensor{'s' if len(sensors) != 1 else ''} ({', '.join(kinds)}); answers each actuator call."


def guardian_line(s: dict) -> str:
    guardian = s.get("guardian", {})
    overrides = guardian.get("overrides", {})
    parts = [f"Judges every reading `{guardian.get('default', 'trusted')}` by default"]
    if overrides:
        parts.append("except " + ", ".join(f"{k}: `{v}`" for k, v in overrides.items()))
    if guardian.get("down") or guardian.get("unavailable"):
        parts.append("and goes silent")
    if "guardian" in s.get("faults", {}):
        parts.append(f"and goes silent after {s['faults']['guardian']['after_verdicts']} verdicts")
    return " ".join(parts) + "."


def render() -> str:
    out = ["# Test Book: the City Brain", "",
           "Generated from `scenarios/` by `scripts/gen_testbook.py`; do not edit by hand. Each scenario is launched by one command (`scenarios/triggers/<id>.sh`, or the number key on the timeline screen) and leaves a log in `logs/`; a verified, repeatable log of each is in `logs/canonical/`.", ""]
    for s in scenarios():
        expect = s.get("expect", {})
        out += [f"## {s['id']}: {s['name']}", "",
                "| Field | |", "| --- | --- |",
                f"| ID | {s['id']} |", f"| Name | {s['name']} |", f"| Layers involved | {', '.join(s.get('layers', []))} |",
                f"| Description | {s.get('description', '')} |",
                f"| Trigger | `./scenarios/triggers/{s['id']}.sh`, or `uv run brain scenario {s['id']}` |",
                f"| Expected: Twin | {twin_line(s)} |", f"| Expected: Guardian | {guardian_line(s)} |",
                f"| Expected: Brain | {s.get('expected_brain', '')} |",
                f"| How to verify | Timeline screen (key `{s['id'][1:]}`); `logs/canonical/{s['id']}.jsonl`; "
                + (f"{s['how_to_verify']} |" if s.get("how_to_verify") else
                   f"`uv run brain scenario {s['id']} --inproc --speed 0` prints each check; `uv run brain replay logs/canonical/{s['id']}.inputs.jsonl` reproduces it |"), ""]
        if expect.get("dispatched") is not None:
            out += [f"Checked: dispatched units {expect['dispatched'] or 'none'}; forbidden events {expect.get('forbidden_events', [])}.", ""]
    out += ["## Which scenario covers which interaction", "",
            "| Interaction (Phase 1) | Scenarios |", "| --- | --- |",
            "| Twin to Brain: a calm day, a crime and a pursuit | d1, d3 |",
            "| Twin to Guardian: a fake reading the Guardian does not trust | d2 |",
            "| Brain to Guardian: every call carries a trusted verdict, or is held | d2, d3 |",
            "| All three: an attack, a flood and a layer down at once | d4 |", ""]
    return "\n".join(out)


if __name__ == "__main__":
    (ROOT / "docs" / "TESTBOOK-brain.md").write_text(render())
    print("wrote docs/TESTBOOK-brain.md")
