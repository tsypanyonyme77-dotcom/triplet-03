"""One registry of read-only tools.

A tool is defined once: a name, a description, the scope a caller needs, and an input schema. The agent team's tools
(`ToolBox` in `departments/team.py`) are registered from the same table its prompts use, so nothing a model sees changes.
Tools the Brain offers other teams' agents (plan P1, the MCP server) register here too, and a partner is then offered exactly
what our own agents have. No tool may take the name of a Twin action: the registry has no way to actuate, only the gate does.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Literal

from brain.contracts import PARAM_MODELS

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}
_PYTHON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool}


class RegistryError(ValueError):
    """A tool was registered twice, named like an actuator, or called with arguments its schema refuses."""


@dataclass(frozen=True)
class Tool:
    name: str
    doc: str
    scope: Literal["read", "analyse"]
    input_schema: dict[str, Any]
    source: Literal["agent", "server"]


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise RegistryError(f"{tool.name} is already registered")
        if tool.name in PARAM_MODELS:
            raise RegistryError(f"{tool.name} is the name of a Twin actuator: tools here only read")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise RegistryError(f"no tool named {name}")
        return self._tools[name]

    def list(self, scope: str | None = None) -> list[Tool]:
        return [t for t in self._tools.values() if scope is None or t.scope == scope]

    def check(self, name: str, args: dict[str, Any]) -> None:
        """Refuse arguments the tool's schema does not allow, with the reason named."""
        schema = self.get(name).input_schema
        for required in schema.get("required", []):
            if required not in args:
                raise RegistryError(f"{name}: missing argument {required}")
        for key, value in args.items():
            if key not in schema["properties"]:
                raise RegistryError(f"{name}: unknown argument {key}")
            expected = _PYTHON_TYPES.get(schema["properties"][key].get("type"))
            if expected and not isinstance(value, expected):
                raise RegistryError(f"{name}: argument {key} must be {schema['properties'][key]['type']}")


def _schema_of(method: Any) -> dict[str, Any]:
    properties, required = {}, []
    for parameter in list(inspect.signature(method).parameters.values())[1:]:  # not `self`
        properties[parameter.name] = {"type": _JSON_TYPES.get(parameter.annotation, "string")}
        if parameter.default is inspect.Parameter.empty:
            required.append(parameter.name)
    return {"type": "object", "properties": properties, "required": required}


def agent_registry() -> Registry:
    """The tools of the agent team, registered from the table its prompts use."""
    from brain.departments.team import TOOL_DESCRIPTIONS, ToolBox

    registry = Registry()
    for name, doc in TOOL_DESCRIPTIONS.items():
        registry.register(Tool(name, doc, "analyse" if name.startswith("solver.") else "read", _schema_of(getattr(ToolBox, name.replace(".", "_"))), "agent"))
    return registry
