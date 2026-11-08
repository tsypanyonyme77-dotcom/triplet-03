"""The Police department's deliberate tier: typed handoffs, the verifier, fallbacks, and LLM wiring."""

import asyncio
import json
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from brain.config import ModelsConfig, Policy
from brain.contracts import Assessment
from brain.departments.police import assess
from brain.departments.team import (
    CaseFile,
    ChiefDecision,
    LLMCrew,
    ScriptedCrew,
    TacticalOption,
    TacticalOptions,
    ToolBox,
    verify_case,
    verify_plan,
)
from brain.knowledge import load_playbook
from brain.knowledge.embedding import HashingEmbedder
from brain.knowledge.memory import MemoryKnowledgeBase
from brain.scenario import inproc_partners, load_scenario, run_scenario

from .test_scenarios import ambiguous_case

POLICY = Policy()


def models(**team) -> ModelsConfig:
    return ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}, "team": team})


async def play(scenario, crew=None, **kwargs):
    kwargs.setdefault("models", models())
    return await run_scenario(scenario, inproc_partners(), speed=0, timeout_s=20, llm_crew=crew, **kwargs)


def modes(result) -> list[str]:
    """What the Brain sent out, in order. Recalls at the end of an incident are left out."""
    return [c["call"]["params"].get("mode", c["call"]["action"]) for c in result.actuator_calls if c["call"]["action"] != "recall_unit"]


class FakeCrew:
    """Stands in for LLMCrew: each role is a coroutine the test supplies; the rest follow the playbook."""

    mode = "llm"

    def __init__(self, **roles) -> None:
        self.roles = roles
        self.scripted = ScriptedCrew(POLICY, "police_station")
        self.briefs: dict[str, list[dict]] = {"analyst": [], "tactician": [], "chief": []}

    async def _run(self, role, brief, tools):
        self.briefs[role].append(brief)
        handler = self.roles.get(role) or getattr(self.scripted, role)
        return await handler(brief, tools)

    async def analyst(self, brief, tools):
        return await self._run("analyst", brief, tools)

    async def tactician(self, brief, tools):
        return await self._run("tactician", brief, tools)

    async def chief(self, brief, tools):
        return await self._run("chief", brief, tools)


def pursue(*cited, confidence="high"):
    async def analyst(brief, tools):
        await tools.graph_entity_timeline(brief["entity_id"])
        return CaseFile(recommendation="pursue", confidence=confidence, summary="s", concerns=[], cited_reading_ids=list(cited))

    return analyst


def offer(*zone_sets):
    """A tactician that offers one perimeter per call, in order, after consulting the cut tool."""
    remaining = list(zone_sets)

    async def tactician(brief, tools):
        await tools.geo_containment_cut(brief["current_zone"], 0)
        zones = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return TacticalOptions(options=[
            TacticalOption(name="perimeter", contain_zones=list(zones), alert_zones=[], rationale="r"),
            TacticalOption(name="pursuit-only", contain_zones=[], alert_zones=[], rationale="r"),
        ])

    return tactician


def choose(*picks):
    remaining = list(picks)

    async def chief(brief, tools):
        option, cites = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        return ChiefDecision(chosen_option=option, playbook_citations=list(cites), justification="because")

    return chief


# --------------------------------------------------------------------------- the verifier in the loop


async def test_a_zone_no_tool_produced_is_rejected_and_the_revision_is_accepted():
    crew = FakeCrew(tactician=offer(["zone-02", "zone-06"], ["zone-04", "zone-08"]), chief=choose(("perimeter", ["POL-PB-002"])))

    result = await play(load_scenario("d3"), crew)

    rejected = result.sink.of("brain.plan.rejected")
    assert len(rejected) == 1 and "zone-02 was not produced by a containment or escape tool" in rejected[0].data["problems"]
    assert crew.briefs["tactician"][1]["feedback"] == rejected[0].data["problems"]  # the objection went back
    assert result.sink.of("brain.plan.verified")[0].data["contain_zones"] == ["zone-04", "zone-08"]
    assert modes(result) == ["pursuit", "contain", "contain"]


async def test_a_plan_that_stays_wrong_is_dropped_and_the_reflex_decision_stands():
    crew = FakeCrew(tactician=offer(["zone-02"]), chief=choose(("perimeter", ["POL-PB-002"])))

    result = await play(load_scenario("d3"), crew)

    assert len(result.sink.of("brain.plan.rejected")) == 2  # the original and one revision
    assert result.sink.of("brain.plan.verified") == []
    assert modes(result) == ["pursuit"]


async def test_the_chief_cannot_commit_the_reserve():
    exits = ["zone-01", "zone-03", "zone-09"]  # the wide perimeter: three units, one more than can be spared

    async def tactician(brief, tools):
        # Planned around where the crime happened, so the test does not depend on how far the suspect has run.
        tight = await tools.geo_containment_cut("zone-07", 0)
        await tools.geo_containment_cut("zone-07", 1)
        return TacticalOptions(options=[
            TacticalOption(name="exit-seal", contain_zones=exits, alert_zones=[], rationale="r"),
            TacticalOption(name="tight", contain_zones=tight["zones"], alert_zones=[], rationale="r"),
        ])

    crew = FakeCrew(tactician=tactician, chief=choose(("exit-seal", ["POL-PB-003"]), ("tight", ["POL-PB-002"])))

    result = await play(load_scenario("d3"), crew)

    problems = result.sink.of("brain.plan.rejected")[0].data["problems"]
    assert problems == ["3 units requested for the perimeter but only 2 can be committed while keeping 1 in reserve"]
    assert result.sink.of("brain.plan.verified")[0].data["option"] == "tight"


@pytest.mark.parametrize(
    ("pick", "problem"),
    [
        (("perimeter", []), "the decision commits resources without citing a playbook item"),
        (("perimeter", ["POL-PB-777"]), "the decision cites playbook items that do not exist: ['POL-PB-777']"),
        (("flood-the-zone", ["POL-PB-002"]), "the Chief chose 'flood-the-zone'; the Tactician offered ['perimeter', 'pursuit-only']"),
    ],
)
async def test_decisions_without_a_real_playbook_basis_are_rejected(pick, problem):
    crew = FakeCrew(tactician=offer(["zone-04", "zone-08"]), chief=choose(pick))

    result = await play(load_scenario("d3"), crew)

    assert problem in result.sink.of("brain.plan.rejected")[0].data["problems"]
    assert modes(result) == ["pursuit"]


async def test_plan_decisions_cite_the_playbook_and_the_graph_remembers():
    result = await play(load_scenario("d3"))

    contain = [e.data for e in result.sink.of("brain.decision.made") if e.data["params"].get("mode") == "contain"]
    assert len(contain) == 2
    for decision in contain:
        assert decision["tier"] == "deliberate"
        assert {"POL-PB-002", "POL-PB-006"} <= set(decision["citations"])
        assert "cam-07-02#1" in decision["citations"] and decision["trust_ref"] in decision["citations"]


# --------------------------------------------------------------------------- ambiguous cases


async def test_an_analyst_can_launch_a_pursuit_the_rules_would_not():
    scenario, policy = ambiguous_case()
    crew = FakeCrew(analyst=pursue("cam-07-02#1", "cit-feed-07#2"), tactician=offer([]), chief=choose(("pursuit-only", [])))

    result = await play(scenario, crew, policy=policy)

    assert modes(result) == ["pursuit"]
    decision = result.sink.of("brain.decision.made")[0].data
    assert decision["tier"] == "deliberate" and "POL-PB-001" in decision["citations"]
    assert crew.briefs["analyst"][0]["assessment"]["level"] == "poi"
    assert "age" not in str(crew.briefs)  # demographic fields never reach a model


@pytest.mark.parametrize(
    ("cited", "problem"),
    [
        (["cam-07-02#1", "made-up#9"], "the case file cites readings that do not exist: ['made-up#9']"),
        (["cam-07-02#1"], "a pursuit needs two trusted sources among the cited readings, found ['cam-07-02']"),
        (["cam-07-02#1", "cit-feed-08#1"], "a pursuit needs two trusted sources among the cited readings, found ['cam-07-02']"),
    ],
)
async def test_a_pursuit_recommendation_the_evidence_does_not_carry_becomes_watch(cited, problem):
    scenario, policy = ambiguous_case()

    result = await play(scenario, FakeCrew(analyst=pursue(*cited)), policy=policy)

    review = result.sink.of("brain.case.reviewed")[0].data
    assert review["recommendation"] == "watch" and problem in review["verifier"]
    assert result.actuator_calls == []


# --------------------------------------------------------------------------- failure and timing


async def test_a_role_whose_model_fails_is_replaced_by_its_stand_in():
    async def broken(brief, tools):
        raise ConnectionError("model unreachable")

    result = await play(load_scenario("d3"), FakeCrew(analyst=broken))

    fallback = result.sink.of("brain.agent.fallback")[0].data
    assert fallback["role"] == "analyst" and "model unreachable" in fallback["error"]
    assert result.sink.of("brain.deliberation.finished")[0].data["modes"] == {"analyst": "scripted", "tactician": "llm", "chief": "llm"}
    assert modes(result) == ["pursuit", "contain", "contain", "broadcast_alert"]


def slow(seconds):
    async def analyst(brief, tools):
        await asyncio.sleep(seconds)
        return await ScriptedCrew(POLICY, "police_station").analyst(brief, tools)

    return analyst


async def test_the_reading_stream_does_not_wait_for_a_deliberating_team():
    scenario = load_scenario("d3")
    scenario["on_dispatch"] = {"pursuit": [{"after_ms": 500, "state": "en_route"}, {"after_ms": 1500, "state": "pursuing"}]}

    result = await play(scenario, FakeCrew(analyst=slow(0.3)), models=models(head_start_s=0.05))

    order = result.sink.types()
    assert order.index("brain.suspect.tracked") < order.index("brain.case.reviewed")
    # While the team was thinking the suspect ran on to the Station, next to an exit. Sealing them in
    # from there would take every unit, so the plan becomes one unit on the likeliest way out.
    plan = result.sink.of("brain.plan.verified")[0].data
    assert (plan["option"], plan["contain_zones"]) == ("intercept", ["zone-09"])
    assert modes(result) == ["pursuit", "contain", "broadcast_alert"]
    # A unit dispatched after the scripted stream ended is still followed up.
    assert [e.data["state"] for e in result.sink.of("brain.unit.status")].count("in_position") == 1


async def test_a_team_still_thinking_when_the_incident_closes_adds_nothing():
    result = await play(load_scenario("d3"), FakeCrew(analyst=slow(0.3)), models=models(head_start_s=0.05))

    order = result.sink.types()
    assert order.index("brain.incident.closed") < order.index("brain.case.reviewed")
    assert result.sink.of("brain.deliberation.finished")[0].data["status"] == "abandoned"
    assert "brain.plan.verified" not in order and modes(result) == ["pursuit"]


async def test_a_deliberation_over_budget_is_abandoned():
    result = await play(load_scenario("d3"), FakeCrew(analyst=slow(0.5)), models=models(budget_s=0.05, head_start_s=0))

    finished = result.sink.of("brain.deliberation.finished")[0].data
    assert finished["status"] == "timeout"
    assert modes(result) == ["pursuit"]
    assert "brain.incident.closed" in result.sink.types()


# --------------------------------------------------------------------------- scripted roles, directly


@pytest.fixture
async def desk(world):
    """A crime with three people at the scene, and the tools to look into it."""
    incident = world.crime(at_s=10)
    for citizen in ("cit-1", "cit-2", "cit-3"):
        world.sighting(citizen, "zone-07", at_s=9)
    kb = MemoryKnowledgeBase(HashingEmbedder())
    await kb.sync(load_playbook("POLICE"))

    def tools() -> ToolBox:
        return ToolBox(world.store, kb, POLICY, incident, "POLICE", {"dispatch_unit", "broadcast_alert"}, "cit-1")

    return world, incident, tools


def brief_for(world, incident, entity) -> dict[str, Any]:
    return {"entity_id": entity, "assessment": assess(incident, entity, world.store, POLICY.scoring).model_dump(mode="json")}


async def test_scripted_analyst_distrusts_flight_when_a_crowd_scatters(desk):
    world, incident, tools = desk
    world.sighting("cit-1", "zone-08", at_s=20, speed=18, activity="running")
    # A doubtful report of a second runner does not change the score, but the Analyst sees it and is careful.
    world.sighting("cit-2", "zone-04", at_s=21, speed=17, activity="running", status="suspicious")
    crew = ScriptedCrew(POLICY, "police_station")

    case = await crew.analyst(brief_for(world, incident, "cit-1"), tools())

    assert (case.recommendation, case.confidence) == ("pursue", "low")
    assert "POL-PB-007" in case.concerns[0]

    decision = await crew.chief({
        "case_file": case.model_dump(), "units_available": 3, "reserve_units": 1,
        "options": [{"name": "tight-perimeter", "contain_zones": ["zone-04", "zone-08"], "alert_zones": [], "rationale": "r"},
                    {"name": "pursuit-only", "contain_zones": [], "alert_zones": [], "rationale": "r"}],
        "playbook": [{"id": "POL-PB-007"}, {"id": "POL-PB-002"}],
    }, tools())
    assert (decision.chosen_option, decision.playbook_citations) == ("pursuit-only", ["POL-PB-007"])


async def test_scripted_analyst_only_watches_when_flight_singles_no_one_out(desk):
    world, incident, tools = desk
    world.sighting("cit-1", "zone-08", at_s=20, speed=18, activity="running")
    world.sighting("cit-2", "zone-04", at_s=21, speed=17, activity="running")

    brief = brief_for(world, incident, "cit-1")
    case = await ScriptedCrew(POLICY, "police_station").analyst(brief, tools())

    assert brief["assessment"]["level"] == "poi" and brief["assessment"]["fled_with"] == ["cit-2"]
    assert case.recommendation == "watch" and "POL-PB-007" in case.concerns[0]
    # An agent that recommends a pursuit anyway is overruled.
    pursue_anyway = case.model_copy(update={"recommendation": "pursue"})
    _, supported, problems = verify_case(pursue_anyway, Assessment.model_validate(brief["assessment"]), tools())
    assert not supported and "a pursuit needs a camera identification" in problems[0]


async def test_scripted_analyst_is_confident_when_independent_sensors_agree(desk):
    world, incident, tools = desk
    world.sighting("cit-1", "zone-08", at_s=20, speed=18, activity="running")

    case = await ScriptedCrew(POLICY, "police_station").analyst(brief_for(world, incident, "cit-1"), tools())

    assert (case.recommendation, case.confidence, case.concerns) == ("pursue", "high", [])


async def test_verifier_only_accepts_what_the_tool_log_supports(desk):
    world, incident, make_tools = desk
    tools = make_tools()
    await tools.geo_containment_cut("zone-07", 0)
    options = [TacticalOption(name="a", contain_zones=["zone-04", "zone-08"], alert_zones=["zone-07"], rationale="r")]
    decision = ChiefDecision(chosen_option="a", playbook_citations=["POL-PB-002"], justification="j")

    accepted = verify_plan(options, decision, tools, units_available=3, reserve_units=1, alert_zones_allowed=["zone-07"])
    no_alert = verify_plan(options, decision, tools, units_available=3, reserve_units=1, alert_zones_allowed=[])
    fresh = verify_plan(options, decision, make_tools(), units_available=3, reserve_units=1, alert_zones_allowed=["zone-07"])

    assert accepted.ok and accepted.contain_zones == ["zone-04", "zone-08"]
    assert no_alert.problems == ["an alert to zone-07 is not allowed for this incident"]
    assert not fresh.ok and len(fresh.problems) == 2  # same plan, but no tool call backs the zones

    for bystander in ("cit-2", "cit-3"):
        world.sighting(bystander, "zone-07", at_s=12)  # seen again after the crime, not running
    assessment = Assessment.model_validate(brief_for(world, incident, "cit-1")["assessment"])
    case = CaseFile(recommendation="pursue", confidence="high", summary="s", concerns=[], cited_reading_ids=assessment.evidence_reading_ids)
    assert verify_case(case, assessment, tools) == (assessment.evidence_reading_ids, True, [])


# --------------------------------------------------------------------------- real LLMCrew, scripted model


class ScriptedChatModel(BaseChatModel):
    """Replays a fixed list of assistant messages, as a tool-calling chat model would produce them."""

    script: list[Any]
    bound: list[Any] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        self.bound.append(sorted(getattr(t, "name", None) or t["name"] for t in tools))
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self.script.pop(0))])


def call(name, **args):
    return {"name": name, "args": args, "id": f"call-{name}"}


async def test_llm_crew_runs_tool_calling_agents_with_structured_answers():
    scripts = {
        "analyst-model": [
            AIMessage(content="", tool_calls=[call("graph_copresence"), call("graph_entity_timeline", entity_id="cit-88213")]),
            AIMessage(content="", tool_calls=[call("CaseFile", recommendation="pursue", confidence="medium", summary="Ran from the scene.",
                                                   concerns=["one reading"], cited_reading_ids=["cam-07-02#1", "cit-feed-07#4"])]),
        ],
        "tactician-model": [
            AIMessage(content="", tool_calls=[call("geo_containment_cut", zone_id="zone-07", lead_hops=0), call("geo_nearest_units", zone_id="zone-07")]),
            AIMessage(content="", tool_calls=[call("TacticalOptions", options=[
                {"name": "tight", "contain_zones": ["zone-04", "zone-08"], "alert_zones": [], "rationale": "two units"},
                {"name": "pursuit-only", "contain_zones": [], "alert_zones": [], "rationale": "none"},
            ])]),
        ],
        "chief-model": [
            AIMessage(content="", tool_calls=[call("ChiefDecision", chosen_option="tight", playbook_citations=["POL-PB-002", "POL-PB-006"],
                                                   justification="Two units seal Downtown and one stays in reserve.")]),
        ],
    }
    built = {spec: ScriptedChatModel(script=script) for spec, script in scripts.items()}
    crew = LLMCrew(
        {"analyst": "analyst-model", "tactician": "tactician-model", "chief": "chief-model"},
        {"analyst": ["graph.incident_evidence", "graph.entity_timeline", "graph.copresence", "kb.search"],
         "tactician": ["geo.nearest_units", "geo.predict_escape", "geo.containment_cut"], "chief": []},
        structured_output="tool", model_factory=lambda spec, **options: built[spec],
    )

    result = await play(load_scenario("d3"), crew)

    assert result.sink.of("brain.agent.fallback") == []
    assert result.sink.of("brain.deliberation.finished")[0].data["modes"] == {"analyst": "llm", "tactician": "llm", "chief": "llm"}
    assert modes(result) == ["pursuit", "contain", "contain"]
    assert "Two units seal Downtown" in result.actuator_calls[1]["call"]["justification"]
    assert built["analyst-model"].bound[0] == ["CaseFile", "graph_copresence", "graph_entity_timeline", "graph_incident_evidence", "kb_search"]
    assert built["chief-model"].bound[0] == ["ChiefDecision"]  # the Chief has no tools, only its decision
    assert all(not model.script for model in built.values())  # every scripted turn was consumed


async def test_a_fast_team_plans_on_the_picture_that_triggered_it():
    """Every event is released at once, yet the plan is the same every time: the loop gives the team a head start."""
    plans = []
    for _ in range(6):
        result = await play(load_scenario("d3"))
        plans.append(result.sink.of("brain.plan.verified")[0].data["contain_zones"])
        assert result.passed, [c.name for c in result.checks if not c.passed]

    assert plans == [["zone-04", "zone-08"]] * 6


async def test_the_head_start_is_bounded():
    import time

    scenario = load_scenario("d3")
    scenario["on_dispatch"] = {"pursuit": [{"after_ms": 500, "state": "en_route"}]}  # the pursuit stays open
    started = time.monotonic()
    result = await play(scenario, FakeCrew(analyst=slow(0.6)), models=models(head_start_s=0.1))

    assert time.monotonic() - started < 3  # one 0.1 s wait, not one per reading
    assert result.sink.of("brain.deliberation.finished")[0].data["status"] == "completed"



def test_each_provider_gets_the_options_that_suit_it():
    models = ModelsConfig.model_validate({
        "roles": {"fast": "groq:openai/gpt-oss-20b", "strong": "ollama:qwen3:8b", "other": "anthropic:claude-haiku-4-5"},
        "role_options": {"other": {"max_tokens": 512}},
    })

    assert models.options_for("fast") == {"temperature": 0, "timeout": 20, "max_retries": 1, "reasoning_effort": "low"}
    assert models.options_for("strong")["num_ctx"] == 8192
    assert models.options_for("other") == {"max_tokens": 512}  # explicit options win
    assert ModelsConfig().roles["strong"].startswith("groq:")


def test_on_groq_the_answer_comes_back_as_a_tool_call():
    """Groq refuses native structured output next to tools, which is what `auto` would otherwise pick."""
    from langchain.agents.structured_output import ToolStrategy

    crew = LLMCrew({"analyst": "groq:openai/gpt-oss-20b", "chief": "elsewhere:model"}, {}, model_factory=lambda spec, **options: None)

    assert isinstance(crew._response_format("analyst", CaseFile), ToolStrategy)
    assert crew._response_format("chief", ChiefDecision) is ChiefDecision  # left to LangChain


def test_asking_for_the_llm_team_without_a_key_stops_with_one_clear_line(monkeypatch):
    from brain.commands.common import _check_llm

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(SystemExit) as stopped:
        _check_llm(ModelsConfig())

    assert "GROQ_API_KEY" in str(stopped.value) and "'fast' role" in str(stopped.value)


def test_an_answer_refused_only_for_its_tool_name_is_recovered():
    from brain.departments.team import _refused_answer

    class Refused(Exception):
        body = {"error": {"code": "tool_use_failed", "failed_generation": json.dumps({"name": "json", "arguments": {
            "recommendation": "pursue", "confidence": "high", "summary": "s", "concerns": [], "cited_reading_ids": ["cam-07-02#1"]}})}}

    class Other(Exception):
        body = {"error": {"code": "rate_limit_exceeded"}}

    assert _refused_answer(Refused(), CaseFile).recommendation == "pursue"
    assert _refused_answer(Other(), CaseFile) is None
    assert _refused_answer(ValueError("plain"), CaseFile) is None


def test_gpt_oss_on_groq_reasons_at_low_effort_and_retries_once():
    models = ModelsConfig.model_validate({"roles": {"fast": "groq:openai/gpt-oss-20b", "other": "groq:qwen/qwen3.8-27b"}})

    assert models.options_for("fast") == {"temperature": 0, "timeout": 20, "max_retries": 1, "reasoning_effort": "low"}
    assert "reasoning_effort" not in models.options_for("other")  # not every Groq model accepts it
