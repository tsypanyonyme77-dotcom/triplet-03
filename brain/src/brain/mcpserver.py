"""The Brain as an MCP server: what another team's agent may read, and nothing it may do.

Tools, resources and a prompt, all read-only: the incidents the Brain holds, why it decided, what surrounds an incident, what its
playbooks say, what the Twin can do. They are registered in the same registry as the agent team's own tools, so a partner is
offered what our agents have. There is no actuating tool and none can be added by name (the registry refuses an actuator's name):
only the gate calls the Twin. A tool that needs more than `read` (the solver's dry run, in plan P2) checks the caller's token scope.
Every call is an event, `brain.mcp.called`.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from brain import config
from brain.explain import explain_decision, explain_incident
from brain.explain.render import to_markdown, to_sentence
from brain.knowledge.context import city_context
from brain.security import Security
from brain.tools.registry import Registry, Tool, agent_registry

OBJECT = {"type": "object", "properties": {}, "required": []}


def _schema(**properties: str) -> dict[str, Any]:
    return {"type": "object", "properties": {k: {"type": t} for k, t in properties.items()}, "required": [k for k in properties if k != "hops" and k != "k"]}


def transport_security(extra_hosts: list[str]) -> TransportSecuritySettings:
    """Keep the SDK's DNS-rebinding protection on: a web page must not be able to call a loopback Brain through the browser."""
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", *extra_hosts]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=hosts,
                                     allowed_origins=[f"http://{h}" for h in hosts] + [f"https://{h}" for h in hosts])


def build_mcp(hub: Any) -> tuple[MCPServer, Registry]:
    security = Security(hub.partners.security)
    registry = agent_registry()
    server = MCPServer("city-brain", instructions="The City Brain: read-only tools over its incidents, explanations, city context and playbooks. It cannot actuate.",
                       log_level="WARNING")

    def running() -> Any:
        if hub.service is None:
            raise ToolError("no run yet: start a scenario or connect the Brain to its partners")
        return hub.service

    def called(tool: str, args: dict[str, Any]) -> None:
        if hub.service is not None:
            hub.service.timeline.emit("brain.mcp.called", None, {"tool": tool, "arguments": args})

    def enter(name: str, scope: str, ctx: Context, args: dict[str, Any]) -> None:
        """Check the caller's scope (`read` is already checked at the edge), then record the call on the timeline."""
        if scope != "read" and not security.allows(scope, dict(getattr(ctx, "headers", None) or {})):
            raise ToolError(f"{name} needs a token with the {scope} scope")
        called(name, args)

    def expose(name: str, doc: str, scope: str, schema: dict[str, Any], fn: Any) -> None:
        registry.register(Tool(name, doc, scope, schema, "server"))
        server.add_tool(fn, name=name, description=doc)

    # ---- tools
    def incidents_list(ctx: Context) -> dict[str, Any]:
        enter("incidents.list", "read", ctx, {})
        return {"incidents": [i.model_dump(mode="json") for i in running().triage.incidents.values()]}

    def incidents_get(incident_id: str, ctx: Context) -> dict[str, Any]:
        enter("incidents.get", "read", ctx, {"incident_id": incident_id})
        incident = running().triage.incidents.get(incident_id)
        if incident is None:
            raise ToolError(f"unknown incident {incident_id}")
        return incident.model_dump(mode="json")

    async def explained(build: Any, key: str) -> dict[str, Any]:
        service = running()
        try:
            built = build(list(hub.broadcaster.buffer), key, policy=hub.policy, kb=service.kb)
        except KeyError:
            raise ToolError(f"nothing in this run to explain for {key}") from None
        return {**built.model_dump(mode="json"), "sentence": to_sentence(built), "markdown": to_markdown(built)}

    async def explain_decision_tool(decision_id: str, ctx: Context) -> dict[str, Any]:
        enter("explain.decision", "read", ctx, {"decision_id": decision_id})
        return await explained(explain_decision, decision_id)

    async def explain_incident_tool(incident_id: str, ctx: Context) -> dict[str, Any]:
        enter("explain.incident", "read", ctx, {"incident_id": incident_id})
        return await explained(explain_incident, incident_id)

    def city_context_tool(incident_id: str, ctx: Context, hops: int = 2) -> dict[str, Any]:
        enter("city.context", "read", ctx, {"incident_id": incident_id, "hops": hops})
        service = running()
        incident = service.store.incident(incident_id)
        if incident is None:
            raise ToolError(f"unknown incident {incident_id}")
        return city_context(service.store, incident, hops=max(0, min(hops, 6))).model_dump(mode="json")

    async def knowledge_search(query: str, ctx: Context, k: int = 4) -> dict[str, Any]:
        enter("knowledge.search", "read", ctx, {"query": query, "k": k})
        kb = running().kb
        hits, _ = await kb.search_traced(query, k=max(1, min(k, 8)))
        return {"hits": [{"id": h.id, "title": kb.title(h.id), "why": h.why, "score": round(h.score, 4)} for h in hits]}

    def capabilities_list(ctx: Context) -> dict[str, Any]:
        enter("capabilities.list", "read", ctx, {})
        return {"actions": sorted(running()._capabilities)}

    expose("incidents.list", "Every incident the Brain holds: type, zone, status, evidence ids.", "read", OBJECT, incidents_list)
    expose("incidents.get", "One incident by id.", "read", _schema(incident_id="string"), incidents_get)
    expose("explain.decision", "Why the Brain decided one thing, built by code from the log: the checks, the margins, what would change it.", "read", _schema(decision_id="string"), explain_decision_tool)
    expose("explain.incident", "Why the Brain responded to an incident as it did, step by step, with the sources and the gate's verdicts.", "read", _schema(incident_id="string"), explain_incident_tool)
    expose("city.context", "The city around an incident: zones within `hops`, nearest stations and their units, who is out, other incidents. No names of people.", "read", _schema(incident_id="string", hops="integer"), city_context_tool)
    expose("knowledge.search", "Search the Brain's playbooks, rules and interface notes. Returns items with their ids.", "read", _schema(query="string", k="integer"), knowledge_search)
    expose("capabilities.list", "The actuator actions the Twin exposes, as the Brain knows them.", "read", OBJECT, capabilities_list)

    # ---- resources and a prompt
    @server.resource("brain://interface-card")
    def interface_card() -> str:
        return (config.home() / "INTERFACE.md").read_text()

    @server.resource("brain://knowledge/{item_id}")
    def knowledge_item(item_id: str) -> str:
        kb = running().kb
        item = kb.items.get(item_id)
        if item is None:
            raise ValueError(f"no knowledge item {item_id}")
        return f"{item.id}: {item.title}\n\n{item.text}"

    @server.resource("brain://schemas/{name}")
    def schema(name: str) -> str:
        import re

        path = config.home() / "contracts" / "schemas" / f"{name}.schema.json"
        if not re.fullmatch(r"[A-Za-z0-9_]{1,60}", name) or not path.exists():
            raise ValueError(f"no schema named {name}")
        return path.read_text()

    @server.prompt()
    async def brief_incident(incident_id: str) -> str:
        """A short briefing on one incident, from the explanation of what the Brain did."""
        return (await explained(explain_incident, incident_id))["markdown"]

    return server, registry
