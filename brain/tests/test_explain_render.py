"""An explanation in words, over HTTP and from the command line."""

import json
import sys

import httpx
import pytest

from brain import cli
from brain.api import Hub, create_app
from brain.config import ModelsConfig, PartnersConfig, Policy
from brain.explain import explain_decision, explain_held, explain_incident
from brain.explain.render import narrate, to_markdown, to_sentence
from tests.test_explain import b2, b3, b11, run  # noqa: F401  (fixtures)

MODELS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})


@pytest.fixture
async def api(tmp_path):
    hub = Hub(PartnersConfig(), Policy(), MODELS, mocks="inproc", log_dir=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        yield client, hub


async def test_the_markdown_states_each_step_with_its_time_and_source(b2):
    e = explain_decision(b2, "dec-0001")

    text = to_markdown(e)

    assert text.startswith("# Send a police unit to pursue cit-88213 from Downtown")
    for step in e.steps:
        assert f"{step.n}. **+{step.at_ms / 1000:.2f} s**" in text and step.fact in text
    assert "Twin" in text and "Guardian" in text and "Brain" in text
    assert "## At the gate" in text and "Passed: trust_ref" in text
    assert "## How close it was" in text and "suspect score" in text
    assert "## What would have changed it" in text and "POL-001" in text


async def test_a_held_action_reads_as_a_refusal_with_its_reason_first(b11):
    held = next(row for row in b11 if row["type"] == "brain.action.blocked")

    text = to_markdown(explain_held(b11, held["id"]))

    assert text.startswith("# Held:")
    assert text.index("## Why it was held") < text.index("## What happened")
    assert "needs 2 independent trusted sources, found 1" in text.split("## What happened")[0]
    assert "A second independent trusted source (1 found, 2 needed)" in text
    assert "human approval" not in text.lower() or "not wired up" in text


async def test_the_sentence_is_short_and_uses_real_plurals(b2, b3, b11):
    one = to_sentence(explain_decision(b2, "dec-0001"))
    held = to_sentence(explain_held(b3, next(r["id"] for r in b3 if r["type"] == "brain.action.blocked")))
    story = to_sentence(explain_incident(b2, "inc-0001"))

    for sentence in (one, held, story):
        assert 3 <= len(sentence.split()) <= 25, sentence
    assert "1 incident" not in story and "6 actions" in story
    assert held.startswith("Held")
    thin = to_sentence(explain_held(b11, next(r["id"] for r in b11 if r["type"] == "brain.action.blocked")))
    assert "1 independent trusted source " in thin + " " and "1 independent trusted sources" not in thin


async def test_an_llm_narration_that_invents_a_figure_is_discarded(b2):
    e = explain_decision(b2, "dec-0001")
    faithful = lambda prompt: "A police unit was sent after cit-88213 because the Guardian trusted verdict-000004."  # noqa: E731
    inventive = lambda prompt: "A police unit was sent after cit-88213 because 97 people agreed."  # noqa: E731
    unknown_id = lambda prompt: "Unit unit-p-77 was sent because verdict-000004 was trusted."  # noqa: E731

    assert narrate(e, faithful) == ("A police unit was sent after cit-88213 because the Guardian trusted verdict-000004.", "llm")
    for bad in (inventive, unknown_id):
        text, mode = narrate(e, bad)
        assert mode == "template" and text == to_sentence(e)
    assert narrate(e, None) == (to_sentence(e), "template")
    assert narrate(e, lambda prompt: (_ for _ in ()).throw(TimeoutError("slow")))[1] == "template"


async def test_the_api_explains_a_decision_a_held_action_and_an_incident(api):
    client, hub = api
    assert (await client.get("/api/decisions/dec-0001/explanation")).status_code == 404  # no run yet

    await client.post("/api/scenarios/d3/run", params={"speed": 0})
    await hub.wait()

    body = (await client.get("/api/decisions/dec-0001/explanation")).json()
    assert body["subject"] == "decision" and body["outcome"] == "acted" and body["steps"][0]["event_type"] == "brain.reading.received"
    assert body["sentence"] and len(body["sentence"].split()) <= 25 and body["narration"] is None
    markdown = await client.get("/api/decisions/dec-0001/explanation", params={"format": "md"})
    assert markdown.headers["content-type"].startswith("text/markdown") and markdown.text.startswith("# Send a police unit")
    story = (await client.get("/api/incidents/inc-0001/explanation")).json()
    assert story["subject"] == "incident" and "apprehended" in story["headline"]
    assert (await client.get("/api/decisions/dec-9999/explanation")).status_code == 404
    assert (await client.get("/api/incidents/inc-9999/explanation")).status_code == 404
    assert (await client.get("/api/held/not-an-event/explanation")).status_code == 404

    await client.post("/api/scenarios/d4/run", params={"speed": 0})
    await hub.wait()
    blocked = next(json.loads(line[6:]) for line in (await client.get("/events", params={"once": True})).text.splitlines()
                   if line.startswith("data: ") and '"brain.action.blocked"' in line)
    held = (await client.get(f"/api/held/{blocked['id']}/explanation")).json()
    assert held["outcome"] == "held" and held["checks"][-1]["check"] == "evidence"


async def test_the_cli_explains_a_saved_log(tmp_path, capsys, monkeypatch):
    result = await run("d3", log_dir=tmp_path)

    def command(*words):
        monkeypatch.setattr(sys, "argv", ["brain", "explain", str(result.log_path), *words])
        with pytest.raises(SystemExit) as exit:
            cli.main()
        return exit.value.code, capsys.readouterr().out

    code, listing = command("--list")
    assert code == 0 and "decision dec-0001" in listing and "incident inc-0001" in listing
    code, text = command("--decision", "dec-0001")
    assert code == 0 and text.startswith("# Send a police unit to pursue cit-88213")
    code, as_json = command("--decision", "dec-0001", "--json")
    assert json.loads(as_json)["id"] == "dec-0001"
    code, one_line = command("--incident", "inc-0001", "--sentence")
    assert "apprehended" in one_line and len(one_line.split()) <= 25
    code, _ = command("--decision", "dec-9999")
    assert code == 1
