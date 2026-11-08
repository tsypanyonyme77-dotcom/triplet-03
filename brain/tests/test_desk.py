"""The department desks: Fire and ambulance, Mobility and Utilities each get an analyst and a chief, checked by code before anything reaches the public."""

import json
from types import SimpleNamespace

from brain.citygraph import MemoryGraphStore
from brain.config import ModelsConfig
from brain.departments import load_manifest
from brain.departments.desk import DeskDecision, DeskReport, ScriptedDesk, verify_desk
from brain.scenario import inproc_partners, load_scenario, run_scenario

MODELS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}, "team": {"departments": "on"}})
KB = SimpleNamespace(has=lambda i: i.startswith("FEM-"))


def city():
    store = MemoryGraphStore()
    store.load_topology({"zones": [{"id": f"zone-0{n}", "name": f"Name {n}"} for n in range(1, 8)],
                         "adjacency": [[f"zone-0{n}", f"zone-0{n + 1}"] for n in range(1, 7)]})
    return store


def report(**over):
    return DeskReport(**{"severity": "high", "summary": "s", "advise_zones": ["zone-03"], **over})


def decide(zones, *, severity="high", send=True, can_alert=True, playbook=("FEM-PB-001",)):
    return verify_desk(DeskDecision(send_advisory=send, zones=zones, justification="j", playbook_ids=list(playbook)), report(severity=severity),
                       store=city(), incident_zone="zone-04", kb=KB, can_alert=can_alert)


def test_every_non_police_department_now_has_an_analyst_and_a_chief():
    for name in ("fire", "medical", "mobility", "disaster", "utilities"):
        assert set(load_manifest(name).agents) == {"analyst", "chief"}


def test_a_zone_near_the_incident_passes_and_one_far_away_or_invented_is_set_aside():
    zones, cited, problems = decide(["zone-03", "zone-07", "zone-99"])

    assert zones == ["zone-03"] and cited == ["FEM-PB-001"] and len(problems) == 2


def test_a_zone_given_by_its_name_is_read_as_that_zone():
    assert decide(["name 3", "Name 5"])[0] == ["zone-03", "zone-05"]


def test_no_more_than_three_zones_are_ever_told():
    zones, _, problems = decide(["zone-02", "zone-03", "zone-05", "zone-06"])

    assert len(zones) == 3 and any("more than 3" in p for p in problems)


def test_a_chief_that_wants_to_send_when_the_analyst_says_low_sends_nothing():
    assert decide(["zone-03"], severity="low")[0] == []


def test_a_playbook_item_that_does_not_exist_is_dropped_and_said():
    _, cited, problems = decide(["zone-03"], playbook=("FEM-PB-001", "MADE-UP-9"))

    assert cited == ["FEM-PB-001"] and any("playbook" in p for p in problems)


def test_nothing_is_sent_when_the_twin_cannot_send_alerts():
    assert decide(["zone-03"], can_alert=False)[:1] == ([],)


async def test_the_scripted_desk_is_deterministic():
    tools = SimpleNamespace(store=city(), kb=KB, graph_context=lambda: _none())
    brief = {"independent_sources": 2, "manifest_severity": 0.9, "incident": {"type": "fire", "zone_id": "zone-04"}, "playbook_hint": []}

    first, second = await ScriptedDesk().analyst(brief, tools), await ScriptedDesk().analyst(brief, tools)

    assert first == second and first.severity == "high" and first.advise_zones == ["zone-03", "zone-05"]


async def _none():
    return None


async def scenario_events(scenario_id, models=MODELS):
    result = await run_scenario(load_scenario(scenario_id), inproc_partners(), models=models, speed=0, timeout_s=30)
    return result, [json.loads(e.model_dump_json(exclude_none=True)) for e in result.sink.events]
