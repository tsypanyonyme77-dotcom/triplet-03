"""The HTTP surface, driven in-process."""

import asyncio
import json
from contextlib import aclosing

import httpx
import pytest

from brain.api import Hub, create_app
from brain.config import ModelsConfig, PartnersConfig, Policy

MODELS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})


@pytest.fixture
async def api(tmp_path):
    hub = Hub(PartnersConfig(), Policy(), MODELS, mocks="inproc", log_dir=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        yield client, hub


async def backlog(client) -> list[dict]:
    response = await client.get("/events", params={"once": True})
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


async def test_nothing_to_show_before_the_first_run(api):
    client, _ = api

    assert (await client.get("/health")).json()["running"] is None
    assert (await client.get("/api/incidents")).status_code == 404
    listing = (await client.get("/api/scenarios")).json()
    assert [s["id"] for s in listing["scenarios"]] == ["t12", "t13", "t14", "t15", "t16"] and listing["runnable"]
    assert (await client.post("/api/scenarios/nope/run")).status_code == 404


async def test_one_trigger_runs_a_scenario_and_everything_about_it_can_be_read_back(api):
    client, hub = api

    started = await client.post("/api/scenarios/t14/run", params={"speed": 0})
    assert started.status_code == 202 and started.json()["run_id"].startswith("t14-")
    assert (await client.post("/api/scenarios/t12/run")).status_code == 409  # one at a time
    await hub.wait()

    listing = (await client.get("/api/scenarios")).json()
    assert listing["last_result"]["passed"], listing["last_result"]
    assert (await client.get("/api/incidents")).json()["incidents"][0]["status"] == "closed"

    events = await backlog(client)
    types = [e["type"] for e in events]
    assert types[0] == "brain.session.reset" and "brain.incident.closed" in types
    assert all(e["specversion"] == "1.0" for e in events)

    decision = (await client.get("/api/decisions/dec-0002")).json()
    assert decision["tier"] == "deliberate" and "POL-PB-002" in decision["knowledge"]
    assert decision["readings"][0] == {**decision["readings"][0], "reading_id": "cam-07-02#1", "verdict": "trusted"}
    assert decision["actions"][0]["result"]["status"] == "dispatched"

    graph = (await client.get("/api/incidents/inc-0001/graph")).json()
    kinds = {node["kind"] for node in graph["nodes"]}
    assert kinds == {"incident", "reading", "verdict", "decision", "action", "knowledge"}
    ids = {node["id"] for node in graph["nodes"]}
    assert all(edge["source"] in ids and edge["target"] in ids for edge in graph["edges"])
    assert (await client.get("/api/topology")).json()["exits"] == ["zone-01", "zone-03", "zone-09"]
    assert (await client.get("/api/decisions/dec-9999")).status_code == 404


async def test_a_new_run_clears_the_screen(api):
    client, hub = api
    await client.post("/api/scenarios/t14/run", params={"speed": 0})
    await hub.wait()
    await client.post("/api/scenarios/t12/run", params={"speed": 0})
    await hub.wait()

    events = await backlog(client)

    assert [e["type"] for e in events].count("brain.session.reset") == 1
    assert "brain.incident.opened" not in [e["type"] for e in events]  # t14's incident is gone


async def test_partner_layers_can_put_their_own_events_on_the_timeline(api):
    client, _ = api
    theirs = {"specversion": "1.0", "source": "guardian", "type": "guardian.sensor.isolated", "subject": "cam-07-02",
              "traceid": "cam-07-02:1", "data": {"reason": "hmac_mismatch"}}

    accepted = await client.post("/api/events", json=theirs)
    forged = await client.post("/api/events", json={**theirs, "source": "city-brain"})
    malformed = await client.post("/api/events", json={"source": "twin"})

    assert accepted.status_code == 202 and forged.status_code == 422 and malformed.status_code == 422
    assert [(e["source"], e["type"]) for e in await backlog(client)] == [("guardian", "guardian.sensor.isolated")]


async def test_the_stream_delivers_events_as_they_happen(api):
    _, hub = api
    received = []

    async def listen():
        async with aclosing(hub.broadcaster.stream()) as stream:  # closing is what a client disconnect does
            async for chunk in stream:
                if chunk.startswith("id:"):
                    received.append(json.loads(chunk.split("data: ", 1)[1]))
                if len(received) == 2:
                    return

    listener = asyncio.create_task(listen())
    await asyncio.sleep(0)
    hub.broadcaster.publish({"id": "1", "type": "a"})
    hub.broadcaster.publish({"id": "2", "type": "b"})
    await asyncio.wait_for(listener, 2)

    assert [e["type"] for e in received] == ["a", "b"]
    assert hub.broadcaster._subscribers == set()  # a closed stream leaves no subscriber behind


async def test_contract_schemas_are_served(api):
    client, _ = api

    names = (await client.get("/schemas")).json()["schemas"]
    assert {"SensorReading", "TrustVerdict", "ActuatorCall", "TimelineEvent"} <= set(names)
    assert (await client.get("/schemas/ActuatorCall")).json()["title"] == "ActuatorCall"
    assert (await client.get("/schemas/..%2Fsecrets")).status_code == 404


async def test_the_timeline_screen_is_served_and_needs_no_network(api):
    client, _ = api

    page = await client.get("/")

    assert page.status_code == 200 and "<title>City Brain" in page.text
    # Nothing on stage may depend on the internet: every URL in the page is embedded or same-origin.
    import re
    external = [u for u in re.findall(r"https?://[^\s\"')]+", page.text) if "www.w3.org" not in u]
    assert external == []
    assert page.text.count("@font-face") == 5 and "url(data:font/woff2;base64," in page.text


async def test_the_3d_library_is_served_by_the_brain_itself_and_nothing_can_escape_its_folder(api):
    client, _ = api

    library = await client.get("/vendor/three/build/three.module.min.js")
    assert library.status_code == 200 and "javascript" in library.headers["content-type"] and "SPDX-License-Identifier: MIT" in library.text[:300]
    assert (await client.get("/vendor/three/LICENSE")).status_code == 200
    assert (await client.get("/vendor/..%2Findex.html")).status_code == 404
    module = await client.get("/canopy3d.js")
    assert module.status_code == 200 and "javascript" in module.headers["content-type"]
    import re
    assert [u for u in re.findall(r"https?://[^\s\"')]+", module.text)] == []  # nothing in the 3D canopy reaches past the Brain
    assert '<script type="module" src="/canopy3d.js"></script>' in (await client.get("/")).text
    # The page maps the bare name "three" to that copy, so the module imports it from the Brain.
    page = (await client.get("/")).text
    assert '"three": "/vendor/three/build/three.module.min.js"' in page


async def test_the_canopy_is_a_directed_city_beside_a_rack_of_instruments(api):
    client, _ = api

    page = (await client.get("/")).text
    module = (await client.get("/canopy3d.js")).text

    assert 'id="mind"' in page and "function renderMind(" in page and "function bandSvg(" in page  # the rack and its prediction band
    assert "togglePause" in page and "toggleFree" in page  # Space pauses the director, F frees the camera
    assert "function direct(" in module and "function shotFor(" in module  # events become shots
    assert 'quality = detectQuality()' in module and "setQuality(" in module and "quality" in module  # high for a real GPU, light otherwise
    assert "UnrealBloomPass" not in module and "EffectComposer" not in module  # the vendored three.js has no addons; the glow pass is written by hand
    assert 'post.on = post.can && quality === "high"' in module and "any(notEqual(c, c))" in module and "post.failed = true" in module  # high tier only, refuses bad pixels, and turns itself off if it draws black


async def test_the_glass_brain_module_is_served_and_imported_by_the_canopy(api):
    client, _ = api

    glass = await client.get("/brainshell.js")
    assert glass.status_code == 200 and "javascript" in glass.headers["content-type"] and "export function buildBrainShell(" in glass.text
    import re
    assert re.findall(r"https?://[^\s\"')]+", glass.text) == []  # nothing is fetched to draw the glass
    assert 'from "/brainshell.js"' in (await client.get("/canopy3d.js")).text


async def test_the_screen_can_explain_a_decision_and_replay_it_through_the_brain(api):
    client, _ = api

    page = (await client.get("/")).text
    module = (await client.get("/canopy3d.js")).text

    assert 'id="why"' in page and "function whySection(" in page and "/explanation" in page  # the panel and the button, fed by the Brain's endpoint
    assert "w: toggleWhy" in page and "heldById" in page  # W explains the newest decision, and a held action can be picked like a decision
    assert "replayThought(" in module and "function thoughtTick(" in module and "stopThought" in module  # the replay through the glass brain
    assert "thought.steps" in module and "routeBetween(" in module  # one shot per run of steps, along the paths events really take


async def test_every_part_of_the_brain_is_named_for_what_it_does_and_explained_in_the_tour(api):
    client, _ = api
    import re

    page = (await client.get("/")).text
    parts = re.findall(r'\{ id: "(\w+)", x: \d+, y: \d+, name: "([^"]+)", who: "([^"]+)"', page)
    assert len(parts) == 11
    guide = page[page.index("const GUIDE = ["):page.index("/* from, to, kind")]
    assert re.findall(r'^  \["(\w+)",', guide, re.M) == ["senses", "forward", "triage", "workspace", "packs", "reflex", "team", "gate", "twin", "memory", "sleep"]  # the order a reading travels
    assert {part for part, _, _ in parts} == set(re.findall(r'^  \["(\w+)",', guide, re.M))
    assert all(name != who for _, name, who in parts)  # the plain name is not the brain's word again
    assert 'id="guide"' in page and "g: toggleGuide" in page


async def test_health_reports_the_configured_default_view(tmp_path):
    from brain.config import BrainConfig

    hub = Hub(PartnersConfig(brain=BrainConfig(default_view="canopy")), Policy(), MODELS, mocks="inproc", log_dir=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        assert (await client.get("/health")).json()["default_view"] == "canopy"


async def test_the_screen_offers_the_dashboard_only_when_one_is_configured(tmp_path):
    from brain.config import ObservabilityConfig

    async def health(partners):
        hub = Hub(partners, Policy(), MODELS, mocks="inproc", log_dir=tmp_path)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
            return (await client.get("/health")).json()["dashboard"], (await client.get("/")).text

    none, page = await health(PartnersConfig())
    url, _ = await health(PartnersConfig(observability=ObservabilityConfig(dashboard_url="http://grafana.localhost:8000/d/city-brain")))

    assert none is None and url == "http://grafana.localhost:8000/d/city-brain"
    assert 'id="observe"' in page and "hidden" in page.split('id="observe"')[1].split(">")[0]


def test_an_unknown_default_view_is_refused_by_the_config():
    from pydantic import ValidationError

    from brain.config import BrainConfig

    with pytest.raises(ValidationError):
        BrainConfig(default_view="hologram")
    assert BrainConfig().default_view == "strip"


async def test_the_last_sleep_report_is_served_when_there_is_one_and_404_when_not(tmp_path):
    from brain.config import BrainConfig

    learned = tmp_path / "learned"
    hub = Hub(PartnersConfig(brain=BrainConfig(learned_dir=str(learned))), Policy(), MODELS, mocks="inproc", log_dir=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        assert (await client.get("/api/sleep/last")).status_code == 404
        learned.mkdir()
        (learned / "last-sleep.json").write_text('{"promoted": [], "rejected": [], "episodes": 3}')
        assert (await client.get("/api/sleep/last")).json()["episodes"] == 3
    bare = Hub(PartnersConfig(), Policy(), MODELS, mocks="inproc", log_dir=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(bare)), base_url="http://brain") as client:
        assert (await client.get("/api/sleep/last")).status_code == 404


async def test_a_sleep_can_be_started_from_the_api_and_its_events_reach_the_stream(tmp_path):
    from brain.config import BrainConfig
    from tests.test_sleep import record

    await record(tmp_path / "episodes")
    partners = PartnersConfig(brain=BrainConfig(episodes_dir=str(tmp_path / "episodes"), learned_dir=str(tmp_path / "learned")))
    hub = Hub(partners, Policy(), MODELS, mocks="inproc", log_dir=tmp_path)
    hub.sleep_suite = ["t12", "t14"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        assert (await client.post("/api/sleep")).status_code == 202
        assert (await client.post("/api/sleep")).status_code == 409
        await hub.wait_sleep()
        types = [e["type"] for e in await backlog(client)]
        report = (await client.get("/api/sleep/last")).json()

    assert types[0] == "brain.sleep.started" and types[-1] == "brain.sleep.finished" and "brain.sleep.rule.promoted" in types
    assert report["promoted"][0]["rule"] == "LRN-1"


async def test_a_sleep_needs_both_folders_configured(tmp_path):
    hub = Hub(PartnersConfig(), Policy(), MODELS, mocks="inproc", log_dir=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        assert (await client.post("/api/sleep")).status_code == 409


async def test_the_model_status_can_be_read_and_the_scripted_team_chosen_and_handed_back(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    hub = Hub(PartnersConfig(), Policy(), MODELS)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        assert (await client.get("/api/llm")).json()["state"] == "live"
        assert (await client.post("/api/llm/mode", json={"mode": "scripted"})).json()["state"] == "scripted"
        assert (await client.post("/api/llm/mode", json={"mode": "auto"})).json()["state"] == "live"
        assert (await client.post("/api/llm/mode", json={"mode": "nonsense"})).status_code == 422
        assert (await client.post("/api/llm/check")).json()["ok"] is None  # no Groq key or model here: only real calls are watched
