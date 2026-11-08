"""`brain replay`: the journal of a run is enough to make the Brain decide the same again."""

import os

import pytest

from brain.baseline import MODELS
from brain.cli import build_parser
from brain.config import Policy
from brain.replay import ReplayRefused, compare, replay
from brain.repro import decisions_of, normalise
from brain.scenario import DEV_SECRETS, inproc_partners, load_scenario, run_scenario


async def record(scenario_id, folder):
    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    folder.mkdir()
    result = await run_scenario(load_scenario(scenario_id), inproc_partners(), models=MODELS, speed=0, timeout_s=30, log_dir=folder, deterministic=True)
    journal = next(folder.glob("*.inputs.jsonl"))
    return result, journal


@pytest.mark.parametrize("scenario_id", ["t14", "t13"])
async def test_replaying_the_journal_gives_the_same_decisions_and_stream(scenario_id, tmp_path):
    result, journal = await record(scenario_id, tmp_path / "run")
    recorded = [e.model_dump(mode="json") for e in result.sink.events]

    replayed = await replay(journal)

    difference = compare(replayed, recorded)
    assert difference.same, difference.first_difference
    assert decisions_of(replayed) == decisions_of(recorded)


async def test_a_deterministic_replay_reproduces_the_recorded_log_records(tmp_path):
    result, journal = await record("t14", tmp_path / "run")
    recorded = [e.model_dump(mode="json") for e in result.sink.events]

    replayed = await replay(journal)

    kept = [e for e in recorded if e["type"] != "brain.scenario.finished"]
    assert [normalise(e) for e in replayed] == [normalise(e) for e in kept]
    assert [e["time"] for e in replayed] == [e["time"] for e in kept]  # the same epoch, the same stamps


async def test_a_tampered_journal_is_refused(tmp_path):
    _, journal = await record("t13", tmp_path / "run")
    lines = journal.read_text().splitlines()
    lines[3] = lines[3].replace('"kind"', '"kinD"', 1)
    journal.write_text("\n".join(lines) + "\n")

    with pytest.raises(ReplayRefused, match="line 4"):
        await replay(journal)


async def test_the_current_config_is_refused_when_it_differs_from_the_recorded_one_unless_allowed(tmp_path):
    _, journal = await record("t13", tmp_path / "run")
    changed = Policy.model_validate({"gate": {"max_actions_per_incident": 1}})

    with pytest.raises(ReplayRefused, match="config"):
        await replay(journal, policy=changed)

    assert await replay(journal, policy=changed, allow_config_change=True)


async def test_a_replay_reports_the_first_difference_when_a_decision_changed(tmp_path):
    result, journal = await record("t14", tmp_path / "run")
    recorded = [e.model_dump(mode="json") for e in result.sink.events]
    changed = Policy.model_validate({"gate": {"max_actions_per_incident": 1}})

    replayed = await replay(journal, policy=changed, allow_config_change=True)

    difference = compare(replayed, recorded)
    assert not difference.same
    assert difference.first_difference


def test_replay_takes_a_journal_and_the_two_switches():
    args = build_parser().parse_args(["replay", "logs/t14.inputs.jsonl", "--current-config", "--allow-config-change"])

    assert (args.journal, args.current_config, args.allow_config_change) == ("logs/t14.inputs.jsonl", True, True)
