"""Retraction: the Guardian takes back a verdict. Later actions that cite the reading stop, and what it taught is revoked."""

import json

import httpx

from brain.api import Hub, create_app
from brain.config import BrainConfig, ModelsConfig, PartnersConfig, Policy
from brain.mind.sleep import Sleeper
from brain.scenario import load_scenario
from brain.timeline import MemorySink, Timeline
from tests.test_conditions import scenario, water
from tests.test_scenarios import play
from tests.test_sleep import SUITE, record


class Retractor:
    """A timeline sink that retracts the evidence of an incident the moment it opens."""

    def __init__(self) -> None:
        self.service = None

    def write(self, event):
        if event.type == "brain.incident.opened" and self.service is not None:
            self.service.retract(event.data["evidence"][0], "the sensor was found to be faulty")


async def test_a_retracted_reading_stops_later_actions_that_cite_it():
    sink = Retractor()

    result = await play(scenario([water(100, 1.3)]), extra_sinks=[sink], on_service=lambda s: setattr(sink, "service", s))

    assert result.actuator_calls == []
    assert {e.data["check"] for e in result.sink.of("brain.action.blocked")} == {"trust_ref"}
    (event,) = result.sink.of("brain.evidence.retracted")
    assert event.subject == "wl-01-01#1" and event.data["incidents"] == ["inc-0001"] and "faulty" in event.data["reason"]


async def test_retracting_an_unknown_reading_changes_nothing():
    holder = Retractor()
    await play(scenario([water(100, 0.4)]), on_service=lambda s: setattr(holder, "service", s))

    assert holder.service.retract("nope#1", "x") is None


async def test_the_api_accepts_a_retraction_and_rejects_an_unknown_reading():
    hub = Hub(PartnersConfig(), Policy(), ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}}), mocks="inproc", log_dir=None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        assert (await client.post("/api/retractions", json={"reading_id": "x#1", "reason": "r"})).status_code == 404
        await client.post("/api/scenarios/t15/run", params={"speed": 0})
        await hub.wait()

        accepted = await client.post("/api/retractions", json={"reading_id": "wl-01-01#5", "reason": "found faulty"})
        unknown = await client.post("/api/retractions", json={"reading_id": "nope#9", "reason": "r"})

    assert accepted.status_code == 202 and accepted.json()["reading_id"] == "wl-01-01#5"
    assert unknown.status_code == 404
    assert hub.service.store.verdict_of("wl-01-01#5").status.value == "untrusted"


async def test_a_retracted_reading_revokes_the_rule_it_taught(tmp_path):
    await record(tmp_path / "episodes")
    sink = MemorySink()
    sleeper = Sleeper(tmp_path / "episodes", tmp_path / "learned", Policy(), Timeline([sink]), suite=SUITE, held_out=[])
    await sleeper.run()
    assert (tmp_path / "learned" / "rules.yaml").exists()

    (tmp_path / "learned" / "retractions.jsonl").write_text(json.dumps({"reading_id": "cam-07-02#1", "reason": "spoofed"}) + "\n")
    again = Sleeper(tmp_path / "episodes", tmp_path / "learned", Policy(), Timeline([sink]), suite=SUITE, held_out=[])
    report = await again.run()

    assert report.revoked == ["LRN-1"]
    assert json.loads((tmp_path / "learned" / "manifest.json").read_text())["rules"] == []
    revoked = [e for e in sink.events if e.type == "brain.sleep.rule.rejected" and e.data["check"] == "revoked"]
    assert revoked and "cam-07-02#1" in revoked[0].data["reason"]


async def test_episodes_with_a_retracted_reading_are_not_mined(tmp_path):
    await record(tmp_path / "episodes")
    (tmp_path / "learned").mkdir()
    (tmp_path / "learned" / "retractions.jsonl").write_text(json.dumps({"reading_id": "cam-07-02#1", "reason": "spoofed"}) + "\n")
    sleeper = Sleeper(tmp_path / "episodes", tmp_path / "learned", Policy(), Timeline([MemorySink()]), suite=SUITE, held_out=[])

    report = await sleeper.run()

    assert report.candidates == 0 and report.promoted == []


async def test_a_retraction_lists_the_episodes_and_rules_that_rest_on_the_reading(tmp_path):
    await record(tmp_path / "episodes")
    await Sleeper(tmp_path / "episodes", tmp_path / "learned", Policy(), Timeline([MemorySink()]), suite=SUITE, held_out=[]).run()
    partners = PartnersConfig(brain=BrainConfig(episodes_dir=str(tmp_path / "episodes"), learned_dir=str(tmp_path / "learned")))
    holder = Retractor()
    result = await play(load_scenario("t14"), partners=partners, on_service=lambda s: setattr(holder, "service", s))

    holder.service.retract("cam-07-02#1", "the camera was found faulty")

    event = result.sink.of("brain.evidence.retracted")[-1]
    assert len(event.data["episodes"]) >= 2 and event.data["rules"] == ["LRN-1"]


async def test_a_retraction_of_a_reading_nothing_stored_rests_on_lists_nothing():
    holder = Retractor()
    result = await play(scenario([water(100, 0.4), water(200, 0.5)]), on_service=lambda s: setattr(holder, "service", s))

    holder.service.retract("wl-01-01#1", "x")

    event = result.sink.of("brain.evidence.retracted")[-1]
    assert event.data["episodes"] == [] and event.data["rules"] == []
