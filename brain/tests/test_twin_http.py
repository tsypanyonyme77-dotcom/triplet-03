"""The Twin over plain HTTP: the same city, the same decisions, the same checks as over MCP."""

import json

import pytest

from brain.adapters import HttpTwinAdapter, open_twin
from brain.config import ModelsConfig, TwinConfig
from brain.scenario import inproc_partners, load_scenario, run_scenario

MODELS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})


def decisions(result):
    return sorted(json.dumps({"action": e.data["action"], "actuator_id": e.data["actuator_id"], "params": e.data["params"]}, sort_keys=True)
                  for e in result.sink.of("brain.decision.made"))


async def play(scenario_id, transport):
    return await run_scenario(load_scenario(scenario_id), inproc_partners(transport=transport), models=MODELS, speed=0, timeout_s=30)


@pytest.mark.parametrize("scenario_id", ["t14", "t13", "t15"])
async def test_the_city_over_http_decides_as_over_mcp(scenario_id):
    over_mcp, over_http = await play(scenario_id, "mcp"), await play(scenario_id, "http")

    assert over_http.passed and over_mcp.passed
    assert decisions(over_http) == decisions(over_mcp)  # b3 decides nothing, on purpose: the same nothing


async def test_the_http_twin_lists_only_the_actuators_it_has():
    async with inproc_partners(frozenset({"set_valve_state"}), transport="http") as (client, _):
        async with HttpTwinAdapter(client) as twin:
            capabilities = await twin.list_capabilities()

    assert "dispatch_unit" in capabilities and "set_valve_state" not in capabilities


def test_the_adapter_in_config_picks_the_carrier():
    assert type(open_twin(TwinConfig(adapter="http", url="http://twin:9000"))).__name__ == "HttpTwinAdapter"
    assert type(open_twin(TwinConfig())).__name__ == "McpTwinAdapter"
