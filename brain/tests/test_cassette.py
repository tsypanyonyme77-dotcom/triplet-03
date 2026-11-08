"""The agent cassette: every model call recorded, so a run with a real model can be played again with no model at all."""

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatResult

from brain.cassette import Cassette, CassetteMiss, CassetteModel
from brain.config import ModelsConfig
from brain.journal import JournalError

SECRET = "cassette-test-secret"
ASK = [SystemMessage("You are the Chief."), HumanMessage('{"incident": "inc-0001"}')]


class Exploding(BaseChatModel):
    """A model that fails if it is ever called: replay must not reach it."""

    @property
    def _llm_type(self) -> str:
        return "exploding"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise AssertionError("the wrapped model was called")


def fake(*replies: str) -> GenericFakeChatModel:
    return GenericFakeChatModel(messages=iter([AIMessage(content=text) for text in replies]))


def wrap(inner, path, mode):
    return CassetteModel(inner=inner, cassette=Cassette(path, mode, SECRET), role="chief", spec="groq:openai/gpt-oss-120b")


async def test_record_then_replay_gives_the_same_reply_without_calling_the_model(tmp_path):
    path = tmp_path / "c.jsonl"

    recorded = await wrap(fake("option: intercept"), path, "record").ainvoke(ASK)
    replayed = await wrap(Exploding(), path, "replay").ainvoke(ASK)

    assert recorded.content == replayed.content == "option: intercept"


async def test_a_changed_brief_is_a_cassette_miss(tmp_path):
    path = tmp_path / "c.jsonl"
    await wrap(fake("option: intercept"), path, "record").ainvoke(ASK)

    with pytest.raises(CassetteMiss):
        await wrap(Exploding(), path, "replay").ainvoke([ASK[0], HumanMessage('{"incident": "inc-0002"}')])


async def test_a_tool_call_sequence_is_replayed_in_order(tmp_path):
    path = tmp_path / "c.jsonl"
    call = AIMessage(content="", tool_calls=[{"name": "geo.nearest_units", "args": {"zone_id": "zone-07"}, "id": "call_1"}])
    followed = [*ASK, call, ToolMessage(content='[{"station": "ps-05"}]', tool_call_id="call_1")]
    model = wrap(GenericFakeChatModel(messages=iter([call, AIMessage(content="send ps-05")])), path, "record")
    first, second = await model.ainvoke(ASK), None
    second = await model.ainvoke(followed)

    replay = wrap(Exploding(), path, "replay")
    assert (await replay.ainvoke(ASK)).tool_calls[0]["name"] == "geo.nearest_units"
    assert (await replay.ainvoke(followed)).content == "send ps-05" == second.content
    assert first.tool_calls[0]["id"] == "call_1"


async def test_a_tampered_cassette_fails_its_chain(tmp_path):
    path = tmp_path / "c.jsonl"
    await wrap(fake("option: intercept"), path, "record").ainvoke(ASK)
    path.write_text(path.read_text().replace("intercept", "ambush"))

    with pytest.raises(JournalError):
        Cassette(path, "replay", SECRET)


async def test_auto_mode_records_only_what_is_missing(tmp_path):
    path = tmp_path / "c.jsonl"
    await wrap(fake("first answer"), path, "record").ainvoke(ASK)
    other = [ASK[0], HumanMessage("a second question")]

    auto = wrap(fake("second answer"), path, "auto")
    assert (await auto.ainvoke(ASK)).content == "first answer"  # a hit: the fake would have said something else
    assert (await auto.ainvoke(other)).content == "second answer"  # a miss: asked, then kept

    assert (await wrap(Exploding(), path, "replay").ainvoke(other)).content == "second answer"


def test_the_team_config_names_a_cassette_and_its_mode_and_is_off_by_default():
    assert ModelsConfig().team.cassette == "off"
    assert ModelsConfig.model_validate({"team": {"cassette": "replay", "cassette_path": "c.jsonl"}}).team.cassette_path == "c.jsonl"


def test_a_crew_with_a_cassette_wraps_every_role_and_replay_builds_no_real_model(tmp_path):
    from brain.departments.team import LLMCrew

    built = []
    path = tmp_path / "c.jsonl"

    def factory(spec, **options):
        built.append(spec)
        return fake("x")

    recording = LLMCrew({"chief": "groq:x"}, {}, "auto", model_factory=factory, cassette=Cassette(path, "record", SECRET))
    assert isinstance(recording._models["chief"], CassetteModel) and built == ["groq:x"]

    LLMCrew({"chief": "groq:x"}, {}, "auto", model_factory=factory, cassette=Cassette(path, "replay", SECRET))
    assert built == ["groq:x"]  # replay needs no model, so no API key and no network


def test_the_cli_turns_the_cassette_flags_into_team_config():
    from brain.cli import build_parser
    from brain.commands.common import _models

    args = build_parser().parse_args(["scenario", "t14", "--cassette", "c.jsonl", "--cassette-mode", "replay"])
    team = _models(args).team

    assert (team.cassette, team.cassette_path, team.llm) == ("replay", "c.jsonl", True)
