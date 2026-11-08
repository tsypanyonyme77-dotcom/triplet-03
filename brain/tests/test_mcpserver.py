"""The Brain as an MCP server: read-only tools, resources and a prompt for other teams' agents, from the same registry our agents use."""

import json
import os
import socket
import threading
import time

import httpx
import uvicorn
from mcp import Client

from brain.api import Hub, create_app
from brain.baseline import MODELS
from brain.config import PartnersConfig, Policy
from brain.contracts import PARAM_MODELS
from brain.mcpserver import build_mcp
from brain.scenario import DEV_SECRETS, inproc_partners, load_scenario, run_scenario


async def hub_after_b2(tmp_path, **partners):
    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    hub = Hub(PartnersConfig.model_validate(partners), Policy(), MODELS, mocks="inproc", log_dir=tmp_path)
    await run_scenario(load_scenario("d3"), inproc_partners(), models=MODELS, speed=0, timeout_s=30, extra_sinks=[hub.broadcaster],
                       on_service=lambda service: setattr(hub, "service", service))
    return hub


def payload(result):
    return json.loads(result.content[0].text)


async def test_the_tool_list_equals_the_server_registry(tmp_path):
    hub = await hub_after_b2(tmp_path)
    server, registry = build_mcp(hub)

    async with Client(server) as client:
        listed = {t.name: t.description for t in (await client.list_tools()).tools}

    assert set(listed) == {t.name for t in registry.list() if t.source == "server"}
    assert {"incidents.list", "incidents.get", "explain.decision", "explain.incident", "city.context", "knowledge.search", "capabilities.list"} <= set(listed)
    assert all(listed[name] == registry.get(name).doc for name in listed)


async def test_no_mcp_tool_can_send_an_actuator_call(tmp_path):
    hub = await hub_after_b2(tmp_path)
    server, _ = build_mcp(hub)

    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}

    assert not names & set(PARAM_MODELS)
    assert not [n for n in names if n.split(".")[-1] in ("dispatch", "actuate", "send", "call")]


async def test_a_partner_can_read_incidents_explanations_and_context(tmp_path):
    hub = await hub_after_b2(tmp_path)
    server, _ = build_mcp(hub)

    async with Client(server) as client:
        incidents = payload(await client.call_tool("incidents.list", {}))["incidents"]
        incident_id = incidents[0]["incident_id"]
        one = payload(await client.call_tool("incidents.get", {"incident_id": incident_id}))
        why = payload(await client.call_tool("explain.incident", {"incident_id": incident_id}))
        around = payload(await client.call_tool("city.context", {"incident_id": incident_id}))
        decision_id = next(e["data"]["decision_id"] for e in hub.broadcaster.buffer if e["type"] == "brain.decision.made")
        decided = payload(await client.call_tool("explain.decision", {"decision_id": decision_id}))

    assert one["incident_id"] == incident_id and why["id"] == incident_id and decided["id"] == decision_id
    assert "zones" in around or "nearest" in str(around).lower() or around


async def test_knowledge_search_returns_playbook_items_with_ids(tmp_path):
    hub = await hub_after_b2(tmp_path)
    server, _ = build_mcp(hub)

    async with Client(server) as client:
        hits = payload(await client.call_tool("knowledge.search", {"query": "pursue a suspect who is fleeing", "k": 3}))["hits"]

    assert 1 <= len(hits) <= 3 and all("id" in h and "title" in h for h in hits)


async def test_an_unknown_incident_is_an_error_result_not_a_crash(tmp_path):
    hub = await hub_after_b2(tmp_path)
    server, _ = build_mcp(hub)

    async with Client(server) as client:
        result = await client.call_tool("incidents.get", {"incident_id": "inc-9999"})

    assert result.is_error and "inc-9999" in result.content[0].text


async def test_a_tool_call_is_written_to_the_timeline_as_brain_mcp_called(tmp_path):
    hub = await hub_after_b2(tmp_path)
    server, _ = build_mcp(hub)
    before = len(hub.broadcaster.buffer)

    async with Client(server) as client:
        await client.call_tool("capabilities.list", {})

    called = [e for e in list(hub.broadcaster.buffer)[before:] if e["type"] == "brain.mcp.called"]
    assert called and called[0]["data"]["tool"] == "capabilities.list" and called[0]["source"] == "city-brain"


async def test_before_any_run_a_tool_says_so(tmp_path):
    hub = Hub(PartnersConfig(), Policy(), MODELS, mocks="inproc", log_dir=tmp_path)
    server, _ = build_mcp(hub)

    async with Client(server) as client:
        result = await client.call_tool("incidents.list", {})

    assert result.is_error and "no run yet" in result.content[0].text


async def test_resources_serve_the_interface_card_and_a_playbook_item(tmp_path):
    hub = await hub_after_b2(tmp_path)
    server, _ = build_mcp(hub)

    async with Client(server) as client:
        card = (await client.read_resource("brain://interface-card")).contents[0].text
        item_id = next(iter(hub.service.kb.items))
        item = (await client.read_resource(f"brain://knowledge/{item_id}")).contents[0].text
        schema = (await client.read_resource("brain://schemas/SensorReading")).contents[0].text

    assert "Interface Card" in card and item_id in item and "properties" in schema


async def test_the_brief_prompt_returns_the_explanation_text(tmp_path):
    hub = await hub_after_b2(tmp_path)
    server, _ = build_mcp(hub)
    incident_id = next(iter(hub.service.triage.incidents))

    async with Client(server) as client:
        prompt = await client.get_prompt("brief_incident", {"incident_id": incident_id})

    assert incident_id in prompt.messages[0].content.text


def test_a_tool_scope_is_enforced_from_the_callers_token(monkeypatch):
    from brain.config import SecurityConfig
    from brain.security import Security

    monkeypatch.setenv("BRAIN_TOKEN_READ", "read-1")
    monkeypatch.setenv("BRAIN_TOKEN_ANALYSE", "analyse-1")
    security = Security(SecurityConfig(require="always"))

    assert security.allows("read", {"authorization": "Bearer read-1"})
    assert not security.allows("analyse", {"authorization": "Bearer read-1"})
    assert security.allows("analyse", {"authorization": "Bearer analyse-1"})
    assert not security.allows("read", {})
    assert Security(SecurityConfig(require="never")).allows("analyse", {})


def serve(app):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    return server, port


async def test_the_mcp_endpoint_is_mounted_on_the_api_and_lists_the_same_tools_over_http(tmp_path):
    hub = await hub_after_b2(tmp_path)
    server, port = serve(create_app(hub))
    try:
        async with Client(f"http://127.0.0.1:{port}/mcp") as client:
            names = {t.name for t in (await client.list_tools()).tools}
    finally:
        server.should_exit = True

    assert "incidents.list" in names


async def test_the_mcp_endpoint_needs_a_token_off_loopback(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_TOKEN_READ", "read-1")
    hub = await hub_after_b2(tmp_path, security={"require": "always"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        refused = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert refused.status_code == 401
