"""Episodes: what the Brain keeps of each closed incident, without identities."""

import json

from brain.config import BrainConfig, PartnersConfig
from brain.mind.episodes import EpisodeStore
from brain.scenario import load_scenario
from tests.test_scenarios import failed, play


def recording(folder) -> PartnersConfig:
    return PartnersConfig(brain=BrainConfig(episodes_dir=str(folder)))


async def test_a_closed_incident_becomes_an_episode_without_identities(tmp_path):
    result = await play(load_scenario("d3"), partners=recording(tmp_path))
    assert result.passed, failed(result)

    episodes, bad = EpisodeStore(tmp_path).all()

    (episode,) = episodes
    assert bad == 0 and episode.incident.type == "crime" and episode.scenario_id == "d3"
    text = json.dumps(episode.model_dump(mode="json"))
    for forbidden in ("cit-88213", "cit-10021", "cit-30577", "wealth", '"age"', "target_id", "unit-p-"):
        assert forbidden not in text, forbidden
    assert [p.reason for p in episode.plans] == ["plan"]
    assert [(a.action, a.params.get("mode"), a.params.get("zone_id")) for a in episode.plans[0].actions][:2] == [
        ("dispatch_unit", "contain", "zone-04"), ("dispatch_unit", "contain", "zone-08")]
    assert [(p.zone_id, p.heading_zone_id) for p in episode.pursuits] == [("zone-07", "zone-08")]
    assert episode.team_runs == 1 and episode.outcome == "apprehended"


async def test_an_episode_keeps_the_guardians_verdict_on_each_reading(tmp_path):
    await play(load_scenario("d3"), partners=recording(tmp_path))

    (episode,), _ = EpisodeStore(tmp_path).all()

    assert episode.readings and all(r.verdict == "trusted" and r.verdict_id.startswith("verdict-") for r in episode.readings)
    assert episode.readings[0].at_ms == 0 and [r.at_ms for r in episode.readings] == sorted(r.at_ms for r in episode.readings)
    assert "unit_status" not in {r.type for r in episode.readings}
    assert {r.type for r in episode.readings} == {"citizen_activity", "cctv_anomaly"}


async def test_the_same_person_keeps_one_alias_inside_an_episode(tmp_path):
    await play(load_scenario("d3"), partners=recording(tmp_path))

    (episode,), _ = EpisodeStore(tmp_path).all()

    people = [r.value["citizen_id"] for r in episode.readings if r.type == "citizen_activity"]
    assert len(set(people)) == 3 and all(p.startswith("p-") for p in people)
    assert people.count(people[1]) >= 3  # the one who loiters and then runs is the same alias each time


async def test_a_corrupt_episode_line_is_skipped_and_counted(tmp_path):
    await play(load_scenario("d3"), partners=recording(tmp_path))
    with (tmp_path / "episodes.jsonl").open("a") as file:
        file.write("{not json\n")
        file.write('{"episode_id": "x"}\n')

    episodes, bad = EpisodeStore(tmp_path).all()

    assert len(episodes) == 1 and bad == 2


async def test_a_run_with_no_episodes_dir_records_nothing(tmp_path):
    await play(load_scenario("d3"))

    assert not list(tmp_path.iterdir())
