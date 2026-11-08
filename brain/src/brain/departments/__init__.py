"""Departments: manifests (what a department may do) and reflex rules (what it does by default)."""

from __future__ import annotations

import operator
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from brain.departments.detectors import Detector


class Bid(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident: str
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    unit: str | None = None  # the kind of unit this incident needs (fire, ambulance, police), if it needs one


class AgentSpec(BaseModel):
    model: str  # a role name from config/models.yaml, e.g. fast or strong
    tools: list[str] = Field(default_factory=list)


class Manifest(BaseModel):
    """A department, or pack: what it reads, may do and detects. Data, so a change of partner is a file edit."""

    model_config = ConfigDict(extra="forbid")  # a misspelt key must not silently drop a detector or an allowlist entry

    code: str
    name: str
    version: str = "1"
    description: str = ""
    subscribes: list[str] = Field(default_factory=list)
    incident_types: list[str] = Field(default_factory=list)
    actuators: list[str] = Field(default_factory=list)
    facility_type: str | None = None
    reflex_rules: str | None = None
    agents: dict[str, AgentSpec] = Field(default_factory=dict)
    # How serious each of its incident types is, for the workspace; falls back to the policy's table.
    severity: dict[str, float] = Field(default_factory=dict)
    detectors: list[Detector] = Field(default_factory=list)
    # How well it fits each incident type (default: 1.0 for each of `incident_types`), and the actuators it
    # cannot answer without (default: every actuator it lists). A pack the Twin cannot serve bids low.
    bids: list[Bid] = Field(default_factory=list)
    needs: list[str] = Field(default_factory=list)

    def allows(self, action: str, params: dict[str, Any]) -> bool:
        """`dispatch_unit:police` allows only that unit type; a bare action name allows any params."""
        qualified = f"{action}:{params.get('unit_type')}" if "unit_type" in params else None
        return action in self.actuators or (qualified is not None and qualified in self.actuators)


class ActionTemplate(BaseModel):
    action: str
    params: dict[str, Any]


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a misspelt key must not silently change what a rule reacts to

    id: str
    name: str
    description: str = ""
    # What the rule is evaluated against, and so which names `when` and `$params` may use:
    #   assessment  one person scored against an incident   {incident, assessment}
    #   scene       the incident as a whole, once per run    {incident, scene}
    #   closed      each unit still out when it closes        {incident, unit}
    #   departed    each perimeter unit of an outrun plan     {incident, unit}
    #   preempted   the perimeter unit taken for another incident's named suspect   {incident, unit}
    #   condition   each open non-crime incident (fire, jam, flood...)  {incident, device}
    #   plan        a suspect just singled out, a plan compiled by sleep    {incident, assessment}
    # (Not called `on`: YAML reads that key as the boolean true.)
    scope: Literal["assessment", "scene", "closed", "departed", "preempted", "condition", "plan"] = "assessment"
    # Set by `load_rules`: the department whose manifest governs what this rule may do.
    department: str | None = None
    # Present on rules that sleep compiled from episodes: where they came from (never read when deciding).
    learned: dict[str, Any] | None = None
    when: dict[str, Any]
    do: list[ActionTemplate]


_OPS = {">=": operator.ge, "<=": operator.le, "!=": operator.ne, ">": operator.gt, "<": operator.lt}


def _lookup(context: dict[str, Any], path: str) -> Any:
    node: Any = context
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def _satisfied(actual: Any, expected: Any) -> bool:
    if isinstance(expected, str):
        for symbol, compare in _OPS.items():
            if expected.startswith(symbol):
                try:
                    return actual is not None and compare(float(actual), float(expected[len(symbol):]))
                except ValueError:
                    return False
    return actual == expected


def matches(rule: Rule, context: dict[str, Any]) -> bool:
    return all(_satisfied(_lookup(context, path), expected) for path, expected in rule.when.items())


def render(template: ActionTemplate, context: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _lookup(context, value[1:]) if isinstance(value, str) and value.startswith("$") else value
        for key, value in template.params.items()
    }


def _read(folder: str, name: str, extra_dir: Path | None = None) -> dict[str, Any]:
    """A built-in file, or the same-named file in the extra folder when there is one (`rules/` for rules)."""
    if extra_dir is not None:
        override = extra_dir / ("rules" if folder == "rules" else "") / name
        if override.is_file():
            return yaml.safe_load(override.read_text())
    return yaml.safe_load(resources.files("brain.departments").joinpath(folder, name).read_text())


def load_manifest(code: str) -> Manifest:
    return Manifest.model_validate(_read("manifests", f"{code.lower()}.yaml"))


def load_rules(file_name: str, department: str | None = None, extra_dir: Path | None = None) -> list[Rule]:
    return [Rule.model_validate({**rule, "department": department}) for rule in _read("rules", file_name, extra_dir)["rules"]]


def load_learned_rules(folder: Path, department: str) -> list[Rule]:
    """The rules `brain sleep` promoted, from `rules.yaml` in the learned folder (none if there is no file)."""
    path = folder / "rules.yaml"
    if not path.is_file():
        return []
    return [Rule.model_validate({**rule, "department": department}) for rule in (yaml.safe_load(path.read_text()) or {}).get("rules", [])]


BUILTIN_PACKS = ("police", "fire", "medical", "mobility", "disaster", "utilities")


def _reason(error: Exception) -> str:
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        return f"{'.'.join(str(p) for p in first['loc']) or 'pack'}: {first['msg']}"
    return f"{type(error).__name__}: {error}".splitlines()[0]


def discover_manifests(extra_dir: Path | None = None) -> tuple[dict[str, Manifest], list[tuple[str, str]]]:
    """Every pack the Brain knows: the built-in ones, then the folder's. A pack with the same code replaces the earlier one.

    A file that cannot be read, has a key the Brain does not know, or names rules that do not load is skipped and
    returned as a (file name, reason) problem: one bad pack must not stop the others, or the Brain.
    """
    packs: dict[str, Manifest] = {}
    problems: list[tuple[str, str]] = []

    def load(name: str, text: str, folder: Path | None) -> None:
        try:
            manifest = Manifest.model_validate(yaml.safe_load(text))
            if manifest.reflex_rules:
                load_rules(manifest.reflex_rules, manifest.code, folder)
        except (yaml.YAMLError, ValidationError, ValueError, OSError, TypeError, KeyError, AttributeError) as error:
            problems.append((name, _reason(error)))
            return
        packs[manifest.code] = manifest

    builtin = resources.files("brain.departments").joinpath("manifests")
    names = sorted((p.name for p in builtin.iterdir() if p.name.endswith(".yaml")),
                   key=lambda n: (BUILTIN_PACKS.index(n[:-5]) if n[:-5] in BUILTIN_PACKS else len(BUILTIN_PACKS), n))
    for name in names:
        load(name, builtin.joinpath(name).read_text(), None)
    if extra_dir is not None and extra_dir.is_dir():
        for path in sorted(extra_dir.glob("*.yaml")):
            load(path.name, path.read_text(), extra_dir)
    return packs, problems
