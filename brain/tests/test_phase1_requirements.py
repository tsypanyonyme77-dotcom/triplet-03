"""The Phase 1 'Required' rules (R1, R2) as tests, so they stay true. See docs/PHASE1-COMPLIANCE.md."""

import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
CARD = (ROOT / "INTERFACE.md").read_text()
SCENARIOS = sorted(p.stem for p in (ROOT / "scenarios").glob("d*.json"))


def test_the_interface_card_fits_one_page():
    assert len(CARD.splitlines()) <= 70 and len(CARD.split()) <= 650, (len(CARD.splitlines()), len(CARD.split()))


def test_the_interface_card_has_what_it_sends_and_receives_how_to_repoint_and_how_it_authenticates():
    headings = [h.lower() for h in re.findall(r"^## (.+)$", CARD, re.M)]

    for needed in ("receives", "sends", "different partner", "authenticat"):
        assert any(needed in h for h in headings), needed


def test_the_interface_card_has_an_example_of_every_message_it_names():
    blocks = re.findall(r"```json\n(.*?)\n```", CARD, re.S)
    parsed = [json.loads(b) for b in blocks]
    keys = [set(p) for p in parsed]

    assert any({"sensor_id", "sequence_no", "value"} <= k for k in keys), "a sensor reading"
    assert any({"verdict_id", "status"} <= k for k in keys), "a trust verdict"
    assert any({"actuator_id", "action", "trust_ref"} <= k for k in keys), "an actuator call"
    assert any(k == {"status", "unit_id", "eta_minutes"} or ("status" in k and "unit_id" in k) for k in keys), "an actuator result"
    assert any({"specversion", "type", "source"} <= k for k in keys), "a timeline event"


def test_the_card_names_the_config_file_not_code_for_repointing():
    assert "config/partners.yaml" in CARD and "no code" in CARD.lower()


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_every_scenario_has_a_trigger_script_that_names_it(scenario_id):
    script = ROOT / "scenarios" / "triggers" / f"{scenario_id}.sh"

    assert script.is_file() and script.stat().st_mode & 0o111, f"{script} is missing or not executable"
    assert f"brain scenario {scenario_id} " in script.read_text() or f"brain scenario {scenario_id}\n" in script.read_text()


def test_every_scenario_has_a_canonical_log_in_the_repository_that_verifies():
    from brain.timeline import verify_chain

    for scenario_id in SCENARIOS:
        log = ROOT / "logs" / "canonical" / f"{scenario_id}.jsonl"
        assert log.is_file(), f"no canonical log for {scenario_id}"
        ok, message = verify_chain(log)
        assert ok, f"{scenario_id}: {message}"


def test_running_a_scenario_leaves_a_log_file_next_to_its_journal(tmp_path):
    import asyncio
    import os

    from brain.baseline import MODELS
    from brain.scenario import DEV_SECRETS, inproc_partners, load_scenario, run_scenario

    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    result = asyncio.run(run_scenario(load_scenario("d1"), inproc_partners(), models=MODELS, speed=0, timeout_s=30, log_dir=tmp_path))

    assert result.log_path.is_file() and result.log_path.with_name(result.log_path.stem + ".inputs.jsonl").is_file()


def test_logs_are_not_ignored_by_git():
    out = subprocess.run(["git", "check-ignore", "-q", "logs/d3-x.jsonl"], cwd=ROOT)

    assert out.returncode == 1  # 1: not ignored


def test_the_readme_names_a_one_command_start():
    readme = (ROOT / "README.md").read_text()

    assert "uv run brain serve" in readme and "uv run brain scenario d3" in readme


def test_the_layout_files_the_phase_1_text_requires_exist_or_are_listed_as_triplet_owned():
    here = ["README.md", "INTERFACE.md", "src", "mocks", "tests", "scenarios", "logs", "docs/diagrams"]
    triplet_owned = ["INTEGRATION.md", "docker-compose.yml"]  # at the triplet root: shared

    assert [f for f in here if not (ROOT / f).exists()] == []
    compliance = (ROOT / "docs" / "PHASE1-COMPLIANCE.md").read_text()
    assert all(name in compliance for name in triplet_owned)


def test_the_test_book_is_generated_from_the_scenario_files_and_lists_every_scenario():
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen_testbook", ROOT / "scripts" / "gen_testbook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = (ROOT / "docs" / "TESTBOOK-brain.md").read_text()

    assert committed == module.render(), "run: uv run python scripts/gen_testbook.py"
    assert all(f"## {s}:" in committed for s in SCENARIOS)
    for field in ("Layers involved", "Trigger", "Expected: Twin", "Expected: Guardian", "Expected: Brain", "How to verify"):
        assert committed.count(f"| {field} |") == len(SCENARIOS)
