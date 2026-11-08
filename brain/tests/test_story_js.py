"""The caption table the screen reads (`story.js`): every event of the four demo scenarios either gets one plain sentence or is left to the Details drawer."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RETIRED = ("forward model", "triage", "salience", "workspace", "reflex", "solver", "counterfactual", "undefined", "NaN", "[object")
node = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")

SCRIPT = """
const {storyOf, STEPS} = require(process.argv[1]);
const state = {zones: new Map([["zone-01", {name: "Harbour"}], ["zone-07", {name: "Downtown"}]])};
const out = [];
for (const file of process.argv.slice(2)) {
  for (const line of require("fs").readFileSync(file, "utf8").split("\\n").filter(Boolean)) {
    const e = JSON.parse(line);
    if (!e.type) continue;
    out.push({type: e.type, story: storyOf(e, state)});
  }
}
console.log(JSON.stringify({steps: STEPS, out}));
"""


def captions(*logs):
    run = subprocess.run(["node", "-e", SCRIPT, str(ROOT / "src/brain/api/static/story.js"), *map(str, logs)], capture_output=True, text=True, check=True)
    return json.loads(run.stdout)


@node
def test_the_relay_has_five_steps_in_the_order_the_jury_is_told():
    assert captions(ROOT / "logs/canonical/t12.jsonl")["steps"] == ["Twin", "Guardian", "Brain", "Safety gate", "City"]


@node
def test_every_demo_event_gets_a_plain_sentence_or_nothing():
    logs = sorted((ROOT / "logs/canonical").glob("d?.jsonl"))
    out = captions(*logs)["out"]

    assert any(row["story"] for row in out)
    for row in out:
        story = row["story"]
        if story is None:
            continue
        assert story["layer"] in ("TWIN", "GUARDIAN", "BRAIN", "GATE", "CITY") and 0 <= story["step"] <= 4 and story["tone"] in ("go", "now", "hold")
        assert story["say"] and story["say"][0].isupper() and story["say"].endswith("."), story
        assert not any(word in story["say"].lower() for word in map(str.lower, RETIRED)), story
        assert story["why"] and story["why"][0].isupper() and story["why"].endswith("."), story
        assert not any(word in story["why"].lower() for word in map(str.lower, RETIRED)), story


@node
def test_a_held_call_reads_as_held_and_names_why():
    out = captions(ROOT / "logs/canonical/t13.jsonl")["out"]
    held = [row["story"] for row in out if row["type"] == "brain.action.blocked"]

    assert held and all(s["tone"] == "hold" and s["layer"] == "GATE" and s["step"] == 3 for s in held)
    assert "trusted Guardian verdict" in held[0]["say"] and "Harbour" in held[0]["say"]


@node
def test_a_guardian_that_goes_quiet_is_said_once_in_plain_words():
    out = captions(ROOT / "logs/canonical/t15.jsonl")["out"]
    quiet = [row["story"] for row in out if row["type"] == "brain.guardian.unavailable"]

    assert len(quiet) == 1 and quiet[0]["layer"] == "GUARDIAN" and quiet[0]["tone"] == "hold" and "stopped answering" in quiet[0]["say"]


@node
def test_an_event_nobody_wrote_a_caption_for_shows_nothing():
    out = captions(ROOT / "logs/canonical/t14.jsonl")["out"]

    assert next(row for row in out if row["type"] == "brain.workspace.released")["story"] is None


@node
def test_each_of_the_five_elements_has_a_job_the_screen_can_say():
    run = subprocess.run(["node", "-e", "const s = require(process.argv[1]); console.log(JSON.stringify({roles: s.ROLES, steps: s.STEPS}))", str(ROOT / "src/brain/api/static/story.js")], capture_output=True, text=True, check=True)
    data = json.loads(run.stdout)

    assert [r["name"] for r in data["roles"]] == data["steps"]
    assert all(len(r["job"]) <= 24 and r["long"].endswith(".") for r in data["roles"])


@node
def test_the_team_steps_each_say_who_does_what():
    out = captions(ROOT / "logs/canonical/t14.jsonl")["out"]
    said = {row["type"]: row["story"]["say"] for row in out if row["story"]}

    assert "Analyst" in said["brain.case.reviewed"] and "Tactician" in said["brain.options.prepared"] and "Chief" in said["brain.plan.verified"]
    assert "Code checks" in said["brain.perimeter.checked"]


@node
def test_the_walkthrough_page_is_the_screens_own_words():
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen_walkthrough", ROOT / "scripts" / "gen_walkthrough.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert (ROOT / "docs/WALKTHROUGH.md").read_text(encoding="utf-8") == module.render(), "run: uv run python scripts/gen_walkthrough.py"
