"""Sleep: episodes in, at most a few promoted reflexes out, and a gate a bad lesson cannot pass."""

import json

import yaml

from brain.config import BrainConfig, PartnersConfig, Policy
from brain.departments import load_learned_rules
from brain.mind.episodes import EpisodeStore
from brain.mind.sleep import Candidate, Sleeper, rollback, sleep
from brain.scenario import load_scenario
from brain.timeline import MemorySink, Timeline
from tests.test_learned_plans import decisions
from tests.test_scenarios import play

SUITE = ["d1", "d3", "d4"]  # a small suite keeps the tests quick; the default is d1 to d4


async def record(folder, scenario_id="d3", runs=2):
    partners = PartnersConfig(brain=BrainConfig(episodes_dir=str(folder)))
    for _ in range(runs):
        await play(load_scenario(scenario_id), partners=partners)


def room(tmp_path, **policy):
    sink = MemorySink()
    sleeper = Sleeper(tmp_path / "episodes", tmp_path / "learned", Policy.model_validate(policy), Timeline([sink]),
                      suite=SUITE, held_out=["d4"])
    return sleeper, sink


async def test_two_runs_of_b2_teach_one_promoted_reflex(tmp_path):
    await record(tmp_path / "episodes")
    sleeper, sink = room(tmp_path)

    report = await sleeper.run()

    (promoted,) = report.promoted
    assert promoted["rule"] == "LRN-1" and report.rejected == [] and report.episodes == 2
    (rule,) = load_learned_rules(tmp_path / "learned", "POLICE")
    assert rule.id == "LRN-1" and rule.scope == "plan" and rule.learned["support"] == 2
    manifest = json.loads((tmp_path / "learned" / "manifest.json").read_text())
    assert sorted(manifest["rules"][0]["sources"]) == sorted(e.episode_id for e in EpisodeStore(tmp_path / "episodes").all()[0])
    assert [c["name"] for c in promoted["checks"]] == ["provenance", "safety", "cap", "rehearsal", "variants", "suite"]
    kinds = [e.type for e in sink.events]
    assert kinds == ["brain.sleep.started", "brain.sleep.rule.proposed", "brain.sleep.rule.promoted", "brain.sleep.finished"]


async def test_a_promoted_reflex_replaces_the_team_run_with_the_same_decisions(tmp_path):
    await record(tmp_path / "episodes")
    await room(tmp_path)[0].run()
    partners = PartnersConfig(brain=BrainConfig(learned_dir=str(tmp_path / "learned")))

    taught = await play(load_scenario("d3"), partners=partners)
    team = await play(load_scenario("d3"))

    assert decisions(taught) == decisions(team)
    assert "brain.deliberation.started" not in taught.sink.types() and taught.sink.of("brain.plan.compiled")


async def test_a_lesson_from_untrusted_evidence_is_rejected_for_provenance(tmp_path):
    await record(tmp_path / "episodes")
    path = tmp_path / "episodes" / "episodes.jsonl"
    edited = []
    for line in path.read_text().splitlines():
        episode = json.loads(line)
        episode["readings"][0]["verdict"] = "untrusted"
        edited.append(json.dumps(episode))
    path.write_text("\n".join(edited) + "\n")
    sleeper, _ = room(tmp_path)

    report = await sleeper.run()

    assert report.promoted == [] and [r["check"] for r in report.rejected] == ["provenance"]
    assert not (tmp_path / "learned" / "rules.yaml").exists()


def broad(do_zone="zone-01"):
    rule = {"id": "CAND-9", "name": "too.broad", "scope": "plan", "when": {"incident.type": "crime", "assessment.level": "suspect"},
            "do": [{"action": "dispatch_unit", "params": {"unit_type": "police", "zone_id": do_zone, "incident_id": "$incident.incident_id",
                                                          "mode": "contain", "target_id": "$assessment.entity_id"}}],
            "learned": {"sources": ["ep-x"], "support": 2}}
    return Candidate(rule=rule, signature=("zone-07", "zone-07", "zone-08"), sources=["ep-x"])


async def test_a_rule_that_changes_a_decision_elsewhere_is_rejected(tmp_path):
    sleeper, _ = room(tmp_path)

    moved = await sleeper.check_suite(broad().rule, [])

    assert "d3" in moved


async def test_the_size_cap_stops_a_flood_of_lessons(tmp_path):
    await record(tmp_path / "episodes")
    sleeper, _ = room(tmp_path, learning={"max_learned_rules": 0})

    report = await sleeper.run()

    assert report.promoted == [] and [r["check"] for r in report.rejected] == ["cap"]


async def test_rollback_removes_the_rule_and_restores_the_teams_plan(tmp_path):
    await record(tmp_path / "episodes")
    await room(tmp_path)[0].run()
    partners = PartnersConfig(brain=BrainConfig(learned_dir=str(tmp_path / "learned")))

    gone = rollback(tmp_path / "learned", "all")
    after = await play(load_scenario("d3"), partners=partners)

    assert gone == ["LRN-1"] and load_learned_rules(tmp_path / "learned", "POLICE") == []
    assert "brain.deliberation.started" in after.sink.types() and after.sink.of("brain.plan.compiled") == []
    assert json.loads((tmp_path / "learned" / "history.jsonl").read_text().splitlines()[-1])["removed"] == ["LRN-1"]


async def test_a_second_sleep_with_nothing_new_promotes_nothing_and_changes_only_the_idle_count(tmp_path):
    await record(tmp_path / "episodes")
    await room(tmp_path)[0].run()
    before = yaml.safe_load((tmp_path / "learned" / "rules.yaml").read_text())["rules"]
    sleeper, _ = room(tmp_path)

    report = await sleeper.run()

    assert report.promoted == [] and report.skipped and report.skipped[0]["reason"] == "already learned" and report.retired == []
    after = yaml.safe_load((tmp_path / "learned" / "rules.yaml").read_text())["rules"]
    strip = lambda rules: [{k: v for k, v in {**r, "learned": {k2: v2 for k2, v2 in r["learned"].items() if k2 not in ("sleeps_idle", "confirmed", "contradicted", "uses", "seen")}}.items()} for r in rules]
    assert strip(after) == strip(before) and after[0]["learned"]["sleeps_idle"] == 1


async def test_a_dry_run_writes_nothing(tmp_path):
    await record(tmp_path / "episodes")
    sleeper, _ = room(tmp_path)

    report = await sleeper.run(dry_run=True)

    assert len(report.promoted) == 1 and not (tmp_path / "learned").exists()


async def test_one_episode_is_not_enough(tmp_path):
    await record(tmp_path / "episodes", runs=1)
    sleeper, _ = room(tmp_path)

    report = await sleeper.run()

    assert report.candidates == 0 and report.promoted == []


async def test_the_sleep_function_takes_a_timeline_and_returns_the_report(tmp_path):
    await record(tmp_path / "episodes")
    sink = MemorySink()

    report = await sleep(tmp_path / "episodes", tmp_path / "learned", Policy(), Timeline([sink]), suite=SUITE, held_out=[])

    assert len(report.promoted) == 1 and sink.types()[-1] == "brain.sleep.finished"
    assert yaml.safe_load((tmp_path / "learned" / "rules.yaml").read_text())["rules"][0]["id"] == "LRN-1"
    assert json.loads((tmp_path / "learned" / "last-sleep.json").read_text())["promoted"][0]["rule"] == "LRN-1"


async def test_a_hand_written_rule_can_still_be_rolled_back(tmp_path):
    from tests.test_learned_plans import B2_PLAN, learned

    learned(tmp_path / "learned", B2_PLAN)  # a rule with only a few provenance fields, as a person might write one

    assert rollback(tmp_path / "learned", "LRN-1") == ["LRN-1"]
    assert load_learned_rules(tmp_path / "learned", "POLICE") == []


async def test_a_learned_rule_fades_after_enough_sleeps_with_nothing_new_and_is_logged(tmp_path):
    await record(tmp_path / "episodes")
    await room(tmp_path)[0].run()
    sink = None
    for _ in range(3):
        sleeper, sink = room(tmp_path, learning={"fade_after_sleeps": 2})
        report = await sleeper.run()

    assert [r["check"] for r in report.retired] == ["faded"] and load_learned_rules(tmp_path / "learned", "POLICE") == []
    rejected = [json.loads(line) for line in (tmp_path / "learned" / "rejected.jsonl").read_text().splitlines()]
    assert rejected[-1]["check"] == "faded" and "has not recurred" in rejected[-1]["reason"]
    assert any(e.type == "brain.sleep.rule.rejected" and e.data["check"] == "faded" for e in sink.events)


async def test_with_the_default_a_learned_rule_never_fades(tmp_path):
    await record(tmp_path / "episodes")
    await room(tmp_path)[0].run()
    for _ in range(4):
        report = await room(tmp_path)[0].run()

    assert report.retired == [] and len(load_learned_rules(tmp_path / "learned", "POLICE")) == 1


async def test_a_run_answered_by_a_learned_plan_is_recorded_as_using_it(tmp_path):
    await record(tmp_path / "episodes")
    await room(tmp_path)[0].run()
    partners = PartnersConfig(brain=BrainConfig(episodes_dir=str(tmp_path / "episodes"), learned_dir=str(tmp_path / "learned")))

    await play(load_scenario("d3"), partners=partners)

    episodes, _ = EpisodeStore(tmp_path / "episodes").all()
    assert episodes[-1].lessons_used == ["LRN-1"] and episodes[-1].plans == []
