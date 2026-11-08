"""One registry of read-only tools: what our agents call is exactly what a partner's agent will be offered."""

import pytest

from brain.contracts import PARAM_MODELS
from brain.departments.team import TOOL_DESCRIPTIONS, ToolBox
from brain.tools.registry import Registry, RegistryError, Tool, agent_registry


def test_every_agent_tool_is_in_the_registry_with_the_same_name_and_description():
    registry = agent_registry()

    assert {t.name for t in registry.list()} == set(TOOL_DESCRIPTIONS)
    assert all(registry.get(name).doc == TOOL_DESCRIPTIONS[name] for name in TOOL_DESCRIPTIONS)
    assert all(t.scope == ("analyse" if t.name.startswith("solver.") else "read") and t.source == "agent" for t in registry.list())  # the solver's dry run needs `analyse`


def test_a_tool_takes_its_input_schema_from_the_method_it_wraps():
    schema = agent_registry().get("graph.entity_timeline").input_schema

    assert schema["properties"]["entity_id"]["type"] == "string" and schema["required"] == ["entity_id"]
    assert agent_registry().get("graph.incident_evidence").input_schema["properties"] == {}


def test_a_call_with_a_bad_argument_is_refused_with_the_schema_error():
    registry = agent_registry()

    with pytest.raises(RegistryError, match="entity_id"):
        registry.check("graph.entity_timeline", {})
    with pytest.raises(RegistryError, match="unknown argument"):
        registry.check("graph.entity_timeline", {"entity_id": "cit-1", "extra": 1})
    registry.check("graph.entity_timeline", {"entity_id": "cit-1"})


def test_no_registered_tool_name_equals_a_twin_action():
    names = {t.name for t in agent_registry().list()}

    assert not names & set(PARAM_MODELS)


def test_a_registered_tool_cannot_be_registered_twice_or_take_a_twin_action_name():
    registry = Registry()
    registry.register(Tool("x.one", "doc", "read", {"type": "object", "properties": {}}, "server"))

    with pytest.raises(RegistryError, match="already"):
        registry.register(Tool("x.one", "doc", "read", {"type": "object", "properties": {}}, "server"))
    with pytest.raises(RegistryError, match="actuator"):
        registry.register(Tool("dispatch_unit", "doc", "read", {"type": "object", "properties": {}}, "server"))


def test_the_registry_lists_tools_by_scope():
    registry = Registry()
    registry.register(Tool("a.read", "d", "read", {"type": "object", "properties": {}}, "server"))
    registry.register(Tool("a.solve", "d", "analyse", {"type": "object", "properties": {}}, "server"))

    assert [t.name for t in registry.list("analyse")] == ["a.solve"]
    assert [t.name for t in registry.list()] == ["a.read", "a.solve"]


def test_every_agent_tool_has_a_toolbox_method():
    assert all(hasattr(ToolBox, name.replace(".", "_")) for name in TOOL_DESCRIPTIONS)
