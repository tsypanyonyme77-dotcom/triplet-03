"""Discovery: a card other agents can read, and a machine-readable description of the event feed."""

import re
from pathlib import Path

import httpx
import yaml

from brain.api import Hub, create_app
from brain.config import ModelsConfig, PartnersConfig, Policy
from brain.contracts import CONTRACT_VERSION

ROOT = Path(__file__).parents[1]
MODELS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})


async def card(**partners):
    hub = Hub(PartnersConfig.model_validate(partners), Policy(), MODELS, mocks="inproc")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        return await client.get("/.well-known/agent-card.json")


async def test_the_agent_card_lists_every_mcp_tool_as_a_skill():
    from brain.mcpserver import build_mcp

    response = await card()
    _, registry = build_mcp(Hub(PartnersConfig(), Policy(), MODELS, mocks="inproc"))

    assert response.status_code == 200
    assert {s["id"] for s in response.json()["skills"]} == {t.name for t in registry.list() if t.source == "server"}


async def test_the_card_names_the_auth_scheme_the_contract_version_and_the_endpoints():
    body = (await card()).json()

    assert body["contract_version"] == CONTRACT_VERSION
    assert body["authentication"]["schemes"] == ["bearer"] and "read" in body["authentication"]["scopes"]
    assert body["endpoints"]["mcp"] == "/mcp" and body["endpoints"]["events"] == "/events"
    assert "brain-inspired" in body["description"].lower() and "never described as conscious" in body["description"]


async def test_the_card_is_public_even_when_tokens_are_required():
    response = await card(security={"require": "always"})

    assert response.status_code == 200


def test_the_asyncapi_file_lists_every_timeline_event_type_the_code_emits():
    described = yaml.safe_load((ROOT / "docs" / "asyncapi.yaml").read_text())["channels"]["events"]["messages"]
    emitted = set()
    for path in (ROOT / "src" / "brain").rglob("*.py"):
        emitted |= set(re.findall(r'emit\(\s*"(brain\.[a-z_.]+)"', path.read_text()))

    assert emitted <= set(described), sorted(emitted - set(described))
