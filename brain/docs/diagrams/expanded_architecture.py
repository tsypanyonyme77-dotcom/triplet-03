"""Writes docs/expanded-architecture.html: the proposed Convergence architecture as one page, diagrams drawn inline.

    uv run python docs/diagrams/expanded_architecture.py

The statements are typed here from docs/superpowers/specs/2026-11-04-convergence-architecture-design.md. Update the spec first,
then this file, then rerun. A box with the accent fill is new in this design; a plain box exists today.
"""

from __future__ import annotations

import math
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain_map import side_view  # noqa: E402  the same drawing as the brain map page
from logo_architecture import incident_flow, tech_map  # noqa: E402  the icon diagrams, shared with the logo page

OUT = Path(__file__).resolve().parents[1] / "expanded-architecture.html"
CHAR = 6.4  # estimated width of one 12.5 px character
TITLE_CHAR = 8.4  # one 15 px bold character


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def measure(width: int, title: str, lines: list[str]) -> tuple[list[str], list[str], int]:
    heads = textwrap.wrap(title, max(8, int((width - 28) / TITLE_CHAR))) or [title]
    body = [row for line in lines for row in textwrap.wrap(line, max(8, int((width - 28) / CHAR)))]
    return heads, body, 16 + 20 * len(heads) + 16 * len(body) + 12


class Box:
    def __init__(self, x: int, y: int, w: int, h: int) -> None:
        self.x, self.y, self.w, self.h = x, y, w, h

    @property
    def cx(self) -> int: return self.x + self.w // 2
    @property
    def cy(self) -> int: return self.y + self.h // 2
    @property
    def right(self) -> int: return self.x + self.w
    @property
    def bottom(self) -> int: return self.y + self.h


class Canvas:
    def __init__(self, width: int, alt: str) -> None:
        self.width, self.alt, self.shapes, self.low = width, alt, [], 0

    def box(self, x: int, y: int, w: int, title: str, lines: list[str], cls: str = "", h: int | None = None) -> Box:
        heads, body, natural = measure(w, title, lines)
        h = h or natural
        out = [f'<rect class="box {cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>']
        for i, row in enumerate(heads):
            out.append(f'<text class="t" x="{x + 14}" y="{y + 26 + 20 * i}">{esc(row)}</text>')
        top = y + 26 + 20 * (len(heads) - 1) + 20
        for i, row in enumerate(body):
            out.append(f'<text class="s" x="{x + 14}" y="{top + 16 * i}">{esc(row)}</text>')
        self.shapes.append("<g>" + "".join(out) + "</g>")
        self.low = max(self.low, y + h)
        return Box(x, y, w, h)

    def row(self, y: int, items: list[tuple], x0: int = 36, x1: int = 1204, gap: int = 10) -> list[Box]:
        """A row of boxes of equal width and the height of the tallest."""
        w = (x1 - x0 - gap * (len(items) - 1)) // len(items)
        h = max(measure(w, item[0], item[1])[2] for item in items)
        return [self.box(x0 + i * (w + gap), y, w, item[0], item[1], item[2] if len(item) > 2 else "", h) for i, item in enumerate(items)]

    def frame(self, x: int, y: int, w: int, h: int, label: str | None = None, cls: str = "") -> None:
        self.shapes.append(f'<rect class="frame {cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="10"/>')
        if label:
            self.shapes.append(f'<text class="k" x="{x + 14}" y="{y + 20}">{esc(label)}</text>')
        self.low = max(self.low, y + h)

    def arrow(self, d: str, cls: str = "") -> None:
        head = "headember" if cls == "ember" else "head"
        self.shapes.append(f'<path class="arrow {cls}" d="{d}" marker-end="url(#{head})"/>')

    def label(self, x: int, y: int, text: str, anchor: str = "start", cls: str = "k") -> None:
        for i, row in enumerate(text.split("\n")):
            self.shapes.append(f'<text class="{cls}" x="{x}" y="{y + 13 * i}" text-anchor="{anchor}">{esc(row)}</text>')

    def svg(self) -> str:
        h = self.low + 16
        defs = ('<defs><marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="headfill"/></marker>'
                '<marker id="headember" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="headember"/></marker></defs>')
        return f'<svg role="img" aria-label="{esc(self.alt)}" viewBox="0 0 {self.width} {h}" width="{self.width}" height="{h}">{defs}{"".join(self.shapes)}</svg>'


def context() -> str:
    c = Canvas(1240, "The City Brain between the Twin and the Guardian. The Twin sends readings to the Brain and, with the Guardian team's Guardian, to the Guardian too. The Guardian sends verdicts to the Brain, audits the Brain's actuator calls on their way to the Twin, and contains devices.")
    top = c.box(400, 10, 440, "Other teams and their agents (Phase 2)", ["Call the Brain's tools over MCP, read its agent card, run the conformance kit against it."], "new")
    a = c.box(414, 156, 204, "Ports and adapters", ["Twin: MCP, HTTP or MQTT. Guardian: REST, or the v1 contract."])
    b = c.box(622, 156, 204, "Senses and trust", ["Contract, signature, replay, forward models, belief."], "new")
    d = c.box(414, 290, 204, "Decide", ["Reflex rules, OR-Tools engines, agent team, planning supervisor."], "new")
    e = c.box(622, 290, 204, "Remember and learn", ["City graph, Qdrant, episodes, sleep, bounded self-improvement."], "new")
    gate = c.box(414, 290 + max(d.h, e.h) + 10, 412, "Gate · the only way out", ["Every call checked and signed. A person approves valve and grid calls."], "gate")
    c.frame(400, 130, 440, gate.bottom + 14 - 130, "CITY BRAIN · THIS REPOSITORY")
    twin = c.box(20, 190, 230, "Twin · city engine", ["The Twin team. Streams readings, runs actuator calls.", "MCP server. Today: a mock."], "partner", 190)
    guardian = c.box(990, 190, 230, "Guardian · trust", ["The Guardian team. Judges every reading, audits actuator calls, quarantines devices.", "REST service. Today: a mock, and the team's own."], "partner", 190)
    ops = c.box(400, gate.bottom + 50, 440, "People and operators", ["The screen over SSE. An approver over REST with a scoped token. Grafana and Jaeger over OTLP and Prometheus."], "new")
    c.arrow(f"M{twin.right} 214 H400")
    c.label(325, 180, "readings\nMCP · HTTP · MQTT", "middle")
    c.arrow(f"M400 296 H{twin.right}", "ember")
    c.label(325, 262, "signed calls\nMCP tools", "middle")
    c.arrow(f"M840 214 H{guardian.x}")
    c.label(915, 180, "ask for a verdict\nREST", "middle")
    c.arrow(f"M{guardian.x} 296 H840")
    c.label(915, 262, "signed verdict\n+ quarantine list", "middle")
    c.arrow(f"M840 344 H{guardian.x}", "ember")
    c.label(915, 312, "audited calls\nv1 only", "middle")
    c.arrow(f"M620 {top.bottom} V130")
    c.label(632, 100, "MCP · A2A card · REST", "start")
    c.arrow(f"M620 {gate.bottom + 14} V{ops.y}")
    c.label(632, gate.bottom + 38, "SSE · REST · OTLP · /metrics", "start")
    y = ops.bottom + 40  # the two links that skip the Brain: the Guardian's own
    c.arrow(f"M1070 {guardian.bottom} V{y} H170 V{twin.bottom}", "ember")
    c.arrow(f"M70 {twin.bottom} V{y + 34} H1170 V{guardian.bottom}")
    c.label(620, y - 8, "v1 only · audited calls forwarded to the Twin (POST /tools/{action}) and containment: isolate, quarantine", "middle")
    c.label(620, y + 52, "v1 only · readings the Twin pushes to the Guardian (POST /v1/readings) or the Guardian pulls · the Guardian forwards none of them to the Brain", "middle")
    c.low = max(c.low, y + 58)
    return c.svg()


def boundary() -> str:
    """Where the line between the Brain's logic and its partners falls, and what sits on each side of it."""
    c = Canvas(1240, "The Brain's logic in the middle, a port on each side, then the adapters and the partners, with the configuration file and the Interface Card below.")
    y0 = 50
    checks = c.box(472, y0 + 40, 312, "Checks on entry", ["Schema, contract version, signature, replay and id pattern. A refusal carries a code and a reason."])
    logic = c.box(472, checks.bottom + 10, 312, "Decision logic", ["Perception, triage, workspace, teams, solvers, safety gate. It knows no protocol."])
    top, bottom = y0, logic.bottom + 14
    c.frame(458, top, 340, bottom - top, "THE BRAIN'S LOGIC")
    h = bottom - top
    twin = c.box(10, top, 190, "Twin", ["Any engine that speaks the Interface Card."], "partner", h)
    ta = c.box(230, top, 190, "Twin adapters", ["One class each: MCP (default), HTTP, MQTT.", "Protocol, TLS and retries stay here.", "With a v1 Guardian a gateway wraps it: audited actions go through the Guardian."], "", h)
    ga = c.box(836, top, 190, "Guardian adapter", ["Two classes: REST (our contract) and v1 (the Guardian team's 1.0).", "A missing or late verdict means no action, never a crash."], "", h)
    guardian = c.box(1056, top, 174, "Guardian", ["Any service that issues a verdict. The team's one is fed by the Twin directly, audits actuator calls and quarantines."], "partner", h)
    for x, name in ((430, "TwinPort"), (808, "GuardianPort")):
        c.frame(x, top, 18, h)
        c.label(x + 9, top - 10, name, "middle")
    mid = top + h // 2
    c.arrow(f"M{twin.right} {mid - 14} H230")
    c.arrow(f"M230 {mid + 22} H{twin.right}", "ember")
    c.arrow(f"M{ta.right} {mid} H458")
    c.arrow(f"M798 {mid} H836")
    c.arrow(f"M{ga.right} {mid - 14} H1056")
    c.arrow(f"M1056 {mid + 22} H{ga.right}")
    yb = bottom + 56
    cfg = c.box(230, yb, 390, "config/partners.yaml", ["Each partner's adapter, address, secret variable name, renames and units. No partner address in the logic."])
    card = c.box(640, yb, 380, "The Interface Card and the contract", ["INTERFACE.md, JSON Schemas, an example of every message. JSON, HMAC-SHA256 or Ed25519, CloudEvents 1.0."])
    conf = c.box(1040, yb, 190, "Conformance kit", ["brain conformance checks a real partner against the card."])
    c.arrow(f"M325 {yb} V{ta.bottom}")
    c.arrow(f"M560 {yb} V{bottom + 28} H931 V{ga.bottom}")
    c.label(342, yb - 10, "read at start-up", "start")
    return c.svg()


def layers() -> str:
    c = Canvas(1240, "Six planes of the Convergence architecture from the interop edge to learning, with the shared spine and the platform underneath. New boxes are filled with the accent.")
    planes = [
        ("1 · INTEROP EDGE · SENSORY INPUT", [
            ("Twin adapter", ["MCP, HTTP or MQTT. Polls or subscribes to readings, calls actuator tools."]),
            ("Guardian adapter", ["REST (ours) or v1 (the Guardian team's). A verdict per reading, quarantine checks, audited calls in v1."]),
            ("API and feed", ["REST, SSE with CloudEvents, schemas, OpenAPI."]),
            ("Brain MCP server", ["Read-only tools, resources, a prompt, scoped by token. No actuating tool."], "new"),
            ("Agent card and conformance kit", ["A2A card. One command checks any Twin or Guardian."], "new"),
            ("Onboarding mapper", ["Proposes renames and units for an unknown Twin. Never edits config."], "new"),
        ]),
        ("2 · SENSES AND TRUST · THALAMIC GATING, CEREBELLAR PREDICTION, THE AMYGDALA'S FAST ROUTE", [
            ("Perception", ["Contract, HMAC, replay, ranges. Drops demographic fields."]),
            ("Forward models", ["Predict each sensor from its history. Doubt a lone outlier."]),
            ("Kalman tracker", ["Level and rate. Time to threshold with an interval."], "new"),
            ("Belief", ["Log-odds fusion of independent witnesses. Advisory."], "new"),
            ("Triage and workspace", ["Seven incident types. Two attention slots."]),
        ]),
        ("3 · UNDERSTANDING · HIPPOCAMPAL INDEX, SEMANTIC MEMORY", [
            ("City graph", ["In memory on the decision path. Neo4j mirror written behind it."]),
            ("Knowledge base", ["Qdrant hybrid search: dense, BM25, payload filters. Memory and Neo4j stay as options."], "new"),
            ("Graph analytics", ["Criticality, communities, N-1 cascade, written back to Neo4j."], "new"),
            ("Context and stories", ["Zone facts. Similar past stories without outcome or identity."]),
        ]),
        ("4 · DECISION · GLOBAL WORKSPACE, REFLEXES AND HABITS, PREFRONTAL DELIBERATION", [
            ("Reflex rules", ["13 rules over six departments. No model."]),
            ("OR-Tools engines", ["Min-cost flow for dispatch. CP-SAT for perimeter and load shedding. Each returns a certificate."], "new"),
            ("Corridor and what-if", ["Time-dependent shortest path, signals held green."], "new"),
            ("Agent team", ["Analyst, Tactician, Chief. Checked by code before the gate."]),
            ("Planning supervisor", ["LangGraph. Solve and deliberate in parallel, reconcile, pause for approval, checkpoint."], "new"),
        ]),
        ("5 · SAFETY · BASAL GANGLIA: HOLD BACK, RELEASE ONE", [
            ("Gate · the only way out", ["Schema, capability, allowlist, incident, trusted verdict, evidence, approval, no repeat, cooling, quarantine, budget."], "gate"),
            ("Signed approval", ["A person approves a valve or grid call. Bound to its parameters, used once."], "new"),
            ("Authentication and red team", ["Scoped tokens, size and rate limits. A suite of attacks that must be refused."], "new"),
        ]),
        ("6 · LEARNING · REPLAY AND CONSOLIDATION IN SLEEP", [
            ("Episodes and sleep", ["Stories become reflexes only after six checks."]),
            ("Academy", ["Tunes listed parameters on held-out stories. 16 after this design, none in the gate."]),
            ("Improvement cycle", ["Benchmarks with a ground truth, verify, promote, audit."], "new"),
        ]),
    ]
    y, edges = 8, []
    for label, items in planes:
        boxes_h = max(measure((1168 - 10 * (len(items) - 1)) // len(items), i[0], i[1])[2] for i in items)
        c.frame(20, y, 1200, boxes_h + 44, label)
        c.row(y + 30, items)
        edges.append((y, y + boxes_h + 44))
        y += boxes_h + 44 + 26
    for (_, bottom), (top, _) in zip(edges, edges[1:]):
        c.arrow(f"M120 {bottom} V{top}", "ember" if top == edges[4][0] else "")
    c.label(134, edges[3][1] + 17, "proposals", "start")
    c.label(134, edges[4][1] + 17, "evidence from every plane", "start")
    c.label(20, y + 6, "SPINE AND PLATFORM, UNDER EVERY PLANE", "start")
    y += 16
    spine = c.row(y, [
        ("Timeline", ["CloudEvents in a hash chain. One trace id per reading."]),
        ("Explain", ["Facts from the log. Counterfactuals proven on the gate. PROV export. Signed bundle."]),
        ("Telemetry", ["OpenTelemetry spans and Prometheus metrics from the same events."], "new"),
        ("Screen", ["Strip Board and the glass-brain canopy. Why panel, approval strip, Optimiser instrument."]),
        ("Journal and replay", ["Every input kept and signed. brain replay reruns it. Agent calls on a cassette."], "new"),
    ])
    y = spine[0].bottom + 10
    c.row(y, [
        ("Images", ["One multi-stage build. Non-root. Embedding model baked in."], "new"),
        ("Compose profiles", ["core, full, mqtt, obs. One command, no network."], "new"),
        ("Full stack", ["make full: Brain, mocks, Neo4j, Qdrant, agents on real models."], "new"),
        ("Hall kit", ["Every image and the model cache in one folder."], "new"),
    ])
    return c.svg()


def planner() -> str:
    c = Canvas(1240, "The planning supervisor graph: assemble context, then solve and deliberate in parallel, reconcile, pause for approval, and pass to the gate. A checkpoint store sits under the graph.")
    trig = c.box(20, 160, 190, "Incident ignites", ["The workspace gives it attention."])
    asm = c.box(250, 160, 190, "assemble", ["City graph, knowledge, Kalman, belief and cascade facts."], "new")
    sol = c.box(500, 40, 230, "solve · milliseconds", ["OR-Tools engines. Certificate with status, objective, gap. Works offline."], "new")
    team = c.box(500, 280, 230, "deliberate · 4 to 9 s", ["The agent team, or the scripted team when there is no network."])
    rec = c.box(790, 160, 190, "reconcile", ["Better feasible plan wins. Regret recorded."], "new")
    app = c.box(1020, 160, 200, "approve · interrupt", ["Pauses for a signed approval. Resumes after a restart."], "new")
    gate = c.box(1020, 360, 200, "Gate", ["Checks and signs every call."], "gate")
    twin = c.box(790, 400, 190, "Twin actuators", ["Only tools the Twin lists."], "partner")
    store = c.box(250, 400, 440, "SQLite checkpoints", ["One thread per incident. Replay a decision from its checkpoints to rebuild its explanation."], "new")
    c.arrow(f"M{trig.right} 200 H{asm.x}")
    c.arrow(f"M{asm.right} 190 H470 V{sol.cy} H{sol.x}")
    c.arrow(f"M{asm.right} 220 H470 V{team.cy} H{team.x}")
    c.arrow(f"M{sol.right} {sol.cy} H760 V190 H{rec.x}")
    c.arrow(f"M{team.right} {team.cy} H760 V220 H{rec.x}")
    c.arrow(f"M{rec.right} 200 H{app.x}")
    c.arrow(f"M{app.cx} {app.bottom} V{gate.y}", "ember")
    c.arrow(f"M{gate.x} {gate.cy} H{twin.right}", "ember")
    c.arrow(f"M{sol.cx} {sol.y} V26 H1000 V{gate.y + 14} H{gate.x}", "ember")
    c.label(sol.cx + 20, 18, "fast path: first proposals reach the gate at once", "start")
    c.label(1120, 140, "high-impact actions only", "middle")
    c.arrow(f"M{app.cx} 100 V{app.y}")
    person = c.box(1020, 12, 200, "A person", ["POST /api/approvals with the approve scope, or the Approve button."], "new")
    c.arrow(f"M{rec.cx} {rec.bottom} V{store.y - 30} H{store.right + 20} V{store.cy} H{store.right}", "")
    return c.svg()


def guardian_wiring() -> str:
    """The same three layers wired two ways that exist, and a third the Brain supports but no Guardian offers."""
    c = Canvas(1240, "Three ways the Guardian can be wired. Panel A: our contract, where the Brain sends each reading to the Guardian and acts on the verdict. Panel B: the Guardian team's contract 1.0, where the Twin also sends readings to the Guardian, the Brain asks for verdicts by id, and valve, grid, signal and dispatch calls pass through the Guardian to the Twin. Panel C: inline, where the verdict rides with the reading; built in the Brain, offered by no Guardian.")

    def panel(y0: int, label: str, v1: bool) -> int:
        twin = c.box(20, y0 + 40, 220, "Twin", ["Streams signed readings, runs actuator calls.", "Today: the Brain's mock."], "partner", 112)
        gua = c.box(1000, y0 + 40, 220, "Guardian", (["Our mock: scripted verdicts, a bad signature is always untrusted."] if not v1 else
                    ["The Guardian team's: six trust layers, signed verdicts, audits every actuator call, checks its effect, quarantines."]), "partner", 112 if not v1 else 150)
        brain = c.box(500, y0 + 215, 240, "City Brain", (["Perception, then the Guardian's verdict, then the gate. Adapter: guardian_rest.py."] if not v1 else
                      ["Adapter: guardian_v1.py. GuardianV1Adapter asks; GuardianGateway routes the gate's calls."]), "", 132)
        c.frame(10, y0, 1220, brain.bottom + 24 - y0, label)
        b = brain.y
        # the Twin side: readings in (outer is deeper and further left), calls out
        c.arrow(f"M160 {twin.bottom} V{b + 26} H{brain.x}")
        c.label(172, b + 20, "readings · MCP, HTTP or MQTT", "start")
        c.arrow(f"M{brain.x} {b + 64} H100 V{twin.bottom}", "ember")
        c.label(172, b + 58, "signed calls · " + ("broadcast, recall" if v1 else "all six actions"), "start")
        # the Guardian side
        c.arrow(f"M{brain.right} {b + 26} H1040 V{gua.bottom}")
        c.label(750, b + 20, "POST /v1/verdicts/request by id" if v1 else "POST /verdicts with the reading", "start")
        c.arrow(f"M1190 {gua.bottom} V{b + 100} H{brain.right}")
        c.label(750, b + 94, "signed verdict" if v1 else "TrustVerdict", "start")
        if v1:
            c.arrow(f"M{brain.right} {b + 64} H1100 V{gua.bottom}", "ember")
            c.label(750, b + 58, "actuator calls: valve, grid, signal, dispatch", "start")
            c.arrow(f"M{twin.right} {twin.y + 30} H{gua.x}")
            c.label(620, twin.y + 22, "POST /v1/readings: the Twin pushes (or the Guardian pulls)", "middle")
            c.arrow(f"M{gua.x} {twin.y + 76} H{twin.right}", "ember")
            c.label(620, twin.y + 68, "POST /tools/{action}: audited calls forwarded, and containment", "middle")
        c.label(750, brain.bottom + 14, "the gate asks GET " + ("/v1/containment" if v1 else "/quarantine/{id}") + " before any call", "start")
        return brain.bottom + 24

    y = panel(8, "A · THE DEFAULT, OUR CONTRACT · guardian.adapter: rest · what the mock Guardian speaks", False) + 18
    y = panel(y, "B · THE GUARDIAN TEAM'S GUARDIAN, CONTRACT 1.0 · guardian.adapter: v1 (gateway: true), twin.dialect: guardian-v1 · run against theirs piece by piece", True) + 18
    c.frame(10, y, 1220, 176, "C · INLINE · guardian.mode: inline · built in the Brain (runtime._verdict), offered by no Guardian, no test")
    tw = c.box(30, y + 36, 200, "Twin", ["Streams readings."], "partner", 96)
    gu = c.box(520, y + 36, 200, "Guardian, inline", ["Judges each reading, attaches the verdict as reading.trust."], "partner", 96)
    br = c.box(1010, y + 36, 200, "City Brain", ["Reads reading.trust and asks nobody. With no trust it asks as in A."], "", 96)
    c.arrow(f"M{tw.right} {tw.cy} H{gu.x}")
    c.label(375, tw.cy - 8, "readings", "middle")
    c.arrow(f"M{gu.right} {gu.cy} H{br.x}")
    c.label(865, gu.cy - 8, "reading + verdict", "middle")
    c.label(30, y + 142, "Not used by the Brain in any panel: the Guardian's WS /v1/ws/verdicts, GET /v1/alerts and GET /v1/threat.\nThe Brain learns of a threat only from a verdict or a quarantine.", "start")
    c.low = max(c.low, y + 182)
    return c.svg()


def deployment() -> str:
    c = Canvas(1240, "Deployment with Docker Compose: a Brain container with persistent state, mock Twin and Guardian, Qdrant and Neo4j containers, optional observability, config as files and secrets from the environment. An offline hall kit sits beside it.")
    c.frame(160, 10, 1060, 520, "DOCKER COMPOSE · PROJECT city-brain · PROFILE full")
    brain = c.box(190, 50, 300, "Brain · container", ["One instance. Health check on /health. Volumes for state and logs. Non-root. Ports: 8080 screen and API, /mcp, /metrics, on 127.0.0.1 only."], "new")
    twin = c.box(520, 50, 210, "Twin mock", ["Optional. Replace by pointing partners.yaml at the real Twin."], "partner")
    gua = c.box(750, 50, 210, "Guardian mock", ["Optional. Same."], "partner")
    job = c.box(980, 50, 220, "Scenario run", ["make full-scenario: brain scenario inside the Brain container, against the services. Exits non-zero on failure."], "new")
    qd = c.box(190, 250, 220, "Qdrant · container", ["Knowledge and episode vectors. Volume."], "new")
    neo = c.box(430, 250, 220, "Neo4j · container", ["City graph, provenance, analytics. Volume."])
    cfg = c.box(670, 250, 250, "Config and .env", ["partners.full.yaml, policy.yaml, models.yaml as files. Keys and tokens from .env, never in an image."], "new")
    net = c.box(940, 250, 260, "Loopback ports", ["Every published port is bound to 127.0.0.1. One private network between the containers."], "new")
    obs_y = 400
    c.label(1200, obs_y - 8, "OBSERVABILITY PROFILE · OPTIONAL ON STAGE", "end")
    otel = c.box(190, obs_y, 220, "OTel collector", ["Receives spans over OTLP."], "new")
    jae = c.box(430, obs_y, 220, "Jaeger", ["One trace per reading."], "new")
    pro = c.box(670, obs_y, 250, "Prometheus", ["Scrapes /metrics."], "new")
    gra = c.box(940, obs_y, 260, "Grafana", ["Provisioned dashboard: gate, solver, retrieval, degraded."], "new")
    browser = c.box(20, 50, 120, "Browser", ["Screen on http://127.0.0.1:8080."], "partner", h=120)
    kit = c.box(20, 300, 120, "Hall kit", ["Images and models. Loads offline."], "new", h=130)
    c.arrow("M140 110 H190")
    c.arrow(f"M470 {brain.bottom} V250")
    c.arrow(f"M{brain.right} 100 H520")
    c.arrow(f"M{twin.right} 100 H750")
    c.arrow(f"M300 {brain.bottom} V250")
    c.arrow(f"M420 {brain.bottom} V380 H300 V{otel.y}", "")
    c.arrow(f"M{otel.right} {otel.cy} H{jae.x}")
    c.arrow(f"M{pro.right} {pro.cy} H{gra.x}")
    c.label(600, 600 - 18, "Compose profiles core, full, mqtt, obs run the same images on one laptop. The core profile is the default on stage.", "middle", "s")
    c.low = max(c.low, 600)
    return c.svg()


def loop() -> str:
    c = Canvas(1240, "The bounded improvement loop: observe, measure, propose, verify, promote, audit, then observe again.")
    cx, cy, rx, ry = 620, 250, 430, 190
    steps = [
        ("Observe", "Closed incidents become episodes. Logs are kept with their hash chain."),
        ("Measure", "Benchmarks with a ground truth: solver regret, retrieval recall, forward-model loss."),
        ("Propose", "Sleep proposes reflexes. The Academy proposes a listed number."),
        ("Verify", "Held-out seeds from 1000, the whole Test Book, the conformance kit, the red-team suite."),
        ("Promote", "A signed overlay, one step at a time, reversible."),
        ("Audit", "A dated report of every check and its result."),
    ]
    boxes = []
    for i, (name, text) in enumerate(steps):
        ang = -math.pi / 2 + i * 2 * math.pi / len(steps)
        boxes.append((int(cx + rx * math.cos(ang)) - 125, int(cy + ry * math.sin(ang)) - 40, name, text))
    centres = [(x + 125, y + 40) for x, y, _, _ in boxes]
    def edge(cx0: float, cy0: float, dx: float, dy: float, gap: float = 0) -> tuple[int, int]:
        k = min(125 / abs(dx) if dx else 1e9, 48 / abs(dy) if dy else 1e9)
        return int(cx0 + dx * k + (dx / math.hypot(dx, dy)) * gap), int(cy0 + dy * k + (dy / math.hypot(dx, dy)) * gap)

    for i in range(len(boxes)):
        (ax, ay), (bx, by) = centres[i], centres[(i + 1) % len(boxes)]
        sx, sy = edge(ax, ay, bx - ax, by - ay, 3)
        ex, ey = edge(bx, by, ax - bx, ay - by, 5)
        c.arrow(f"M{sx} {sy} L{ex} {ey}")
    for x, y, name, text in boxes:
        c.box(x, y, 250, name, [text], "new" if name in ("Measure", "Verify", "Audit") else "", h=96)
    c.label(cx, cy - 22, "BOUNDED", "middle")
    c.label(cx, cy + 0, "16 listed parameters.", "middle", "t")
    c.label(cx, cy + 20, "The gate, tactics, suspect scoring, triage,", "middle", "s")
    c.label(cx, cy + 36, "learning and the optimiser are not on the list.", "middle", "s")
    c.label(cx, cy + 56, "No signal from the outcome of a dispatch.", "middle", "s")
    return c.svg()


PLANE_ROWS = "<tr><td>1 Interop edge</td><td>Senses (input side)</td><td>Sensory input, before any judgement</td><td>Brain MCP server, agent card, conformance kit, onboarding mapper: none claimed</td><td>The edge is protocol work; no brain has an Interface Card</td></tr><tr><td>2 Senses and trust</td><td>Senses, forward models, triage</td><td>Thalamic gating by reliability; cerebellar forward models and prediction error; the amygdala's fast route</td><td>Kalman tracker (cerebellar state estimation); belief (evidence accumulated as log-likelihood ratios); corollary discharge (built, off)</td><td>Surprise is a z-score; the learning rate is fixed so an attacker cannot teach a spike</td></tr><tr><td>3 Understanding</td><td>Memory</td><td>Hippocampal index of episodes; semantic memory</td><td>Qdrant stories (pattern completion from a partial cue); graph analytics (a cognitive map, loose)</td><td>The record never changes; a brain rewrites memories on recall</td></tr><tr><td>4 Decision</td><td>Workspace, packs, reflex, team</td><td>Global workspace with ignition and broadcast; specialised modules; reflexes and habits; prefrontal goals with conflict monitoring</td><td>OR-Tools engines (none claimed); the planning supervisor (arbitration between a fast habit and slow deliberation)</td><td>The three agent roles are an incident-command analogy; the 'cingulate' is code</td></tr><tr><td>5 Safety</td><td>Gate</td><td>Basal ganglia: everything held back, the winner released, a brake under conflict</td><td>Signed approval: a person outside the system, where the metaphor stops</td><td>A learned gate was rejected; the gate is code</td></tr><tr><td>6 Learning</td><td>Sleep, memory</td><td>Replay and consolidation; tag and capture; useful forgetting</td><td><code>brain improve</code> (homeostasis, loose)</td><td>No reward signal: learning from outcomes could be taught by an attacker</td></tr><tr><td>Spine and platform</td><td>none</td><td>None: deliberately not biological</td><td>Input journal, agent cassette, hash chain, replay, images, Compose</td><td>Brains reconstruct; the Brain replays bytes</td></tr>"

PAGE = """<title>Convergence Architecture</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Familjen+Grotesk:wght@500;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: one reading column; diagrams and tables break out wider and scroll inside themselves. Accent fill marks what is new in this design; amber marks the gate. */
:root { --bg:#F2F4F5; --panel:#FFFFFF; --fg:#10161C; --muted:#51606D; --line:#C5CED5; --steel:#31597E; --ember:#A8590A; --good:#17724A; --wash:#E6EBEE; --new:#DCE8F3;
  --display:'Familjen Grotesk','Helvetica Neue',Arial,sans-serif; --body:'IBM Plex Sans','Helvetica Neue',Arial,sans-serif; --mono:'IBM Plex Mono',ui-monospace,Menlo,monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0B1118; --panel:#121A23; --fg:#E8E5DA; --muted:#9AA8B5; --line:#2B3947; --steel:#7FA3C4; --ember:#F2B552; --good:#4CC38A; --wash:#18222D; --new:#1B2D41; color-scheme: dark; } }
:root[data-theme="dark"] { --bg:#0B1118; --panel:#121A23; --fg:#E8E5DA; --muted:#9AA8B5; --line:#2B3947; --steel:#7FA3C4; --ember:#F2B552; --good:#4CC38A; --wash:#18222D; --new:#1B2D41; color-scheme: dark; }
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--fg); font: 16px/1.55 var(--body); padding-block: 40px 96px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
main { max-width: 1240px; margin: 0 auto; display: flex; flex-direction: column; gap: 64px; }
header, section > :not(.wide) { max-width: 72ch; }
h1 { font: 700 clamp(2.4rem, 6vw, 4rem)/1.02 var(--display); letter-spacing: -.02em; margin: 0 0 16px; text-wrap: balance; }
h2 { font: 700 1.7rem/1.15 var(--display); letter-spacing: -.01em; margin: 0 0 14px; text-wrap: balance; }
h3 { font: 600 .78rem/1.3 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 28px 0 8px; }
p { margin: 0 0 12px; } .lead { font-size: 1.15rem; }
.date { font: 500 .85rem var(--mono); color: var(--muted); letter-spacing: .04em; margin-bottom: 14px; }
.wide { max-width: none; overflow-x: auto; border: 1px solid var(--line); background: var(--panel); border-radius: 6px; margin-bottom: 12px; }
.wide svg { display: block; min-width: 1000px; width: 100%; height: auto; }
.box { fill: var(--panel); stroke: var(--steel); stroke-width: 1.4; } .box.new { fill: var(--new); } .box.partner { stroke-dasharray: 6 4; stroke: var(--muted); fill: var(--wash); } .box.gate { stroke: var(--ember); stroke-width: 2.4; fill: var(--wash); }
.frame { fill: none; stroke: var(--line); stroke-width: 1.2; }
.card { fill: var(--panel); stroke: var(--line); stroke-width: 1.4; } .card.new { fill: var(--new); stroke: var(--steel); } .card.partner { stroke-dasharray: 6 4; stroke: var(--muted); fill: var(--wash); } .card.gate { stroke: var(--ember); stroke-width: 2.4; fill: var(--wash); } .tile { fill: #FFFFFF; stroke: #D5DCE1; stroke-width: 1; } .glyph { fill: none; stroke: #31597E; stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; } svg .an { font: 500 10.5px var(--mono); fill: var(--steel); letter-spacing: .03em; } svg .row { font: 700 13px var(--mono); fill: var(--muted); letter-spacing: .12em; }
.cortex, .cbl, .stem { fill: var(--wash); stroke: var(--steel); stroke-width: 1.3; } .cbl { stroke-dasharray: 3 4; } .wire { fill: none; stroke: var(--steel); stroke-width: 1.5; opacity: .7; } .wire.out { stroke: var(--ember); opacity: 1; stroke-width: 2; } .tipfill { fill: var(--steel); } .dot { fill: var(--steel); } .dot.gate { fill: var(--ember); } .dot.agent { fill: #6B4FA0; } .dot.twin { fill: var(--muted); } .arrow { fill: none; stroke: var(--steel); stroke-width: 1.8; } .arrow.ember { stroke: var(--ember); } .headfill { fill: var(--steel); } .headember { fill: var(--ember); }
svg .t { font: 600 15px var(--body); fill: var(--fg); } svg .s { font: 400 12.5px var(--body); fill: var(--muted); } svg .k { font: 500 11px var(--mono); fill: var(--muted); letter-spacing: .06em; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 20px; font-size: .9rem; color: var(--muted); margin: 0 0 12px; max-width: none; }
.legend span::before { content: ""; display: inline-block; width: 18px; height: 12px; margin-right: 7px; vertical-align: -1px; border: 1.4px solid var(--steel); border-radius: 3px; background: var(--panel); }
.legend .n::before { background: var(--new); } .legend .p::before { border-style: dashed; border-color: var(--muted); background: var(--wash); } .legend .g::before { border-color: var(--ember); border-width: 2px; background: var(--wash); }
ol.flow { margin: 0; padding: 0; list-style: none; counter-reset: step; border-left: 2px solid var(--steel); }
ol.flow li { counter-increment: step; padding: 8px 0 8px 22px; position: relative; } ol.flow li::before { content: counter(step); position: absolute; left: -15px; top: 8px; width: 28px; height: 28px; border-radius: 50%; background: var(--bg); border: 2px solid var(--steel); font: 500 .8rem/24px var(--mono); text-align: center; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; } th, td { text-align: left; vertical-align: top; padding: 10px 14px; border-top: 1px solid var(--line); min-width: 7rem; } th { font: 500 .74rem var(--mono); text-transform: uppercase; letter-spacing: .07em; color: var(--muted); border-top: 0; background: var(--wash); }
td:first-child { font-weight: 600; } td.num { font-family: var(--mono); font-size: .86em; white-space: nowrap; }
.tag { display: inline-block; font: 500 .72rem var(--mono); letter-spacing: .04em; padding: 1px 7px; border: 1.5px solid currentColor; border-radius: 3px; white-space: nowrap; }
.tag.ok { color: var(--good); } .tag.open { color: var(--ember); } .tag.off { color: var(--muted); }
code { font: 500 .88em var(--mono); background: var(--wash); padding: 1px 5px; border-radius: 3px; }
ul.plain { margin: 0; padding-left: 1.2em; } ul.plain li { margin-bottom: 6px; }
footer { color: var(--muted); font-size: .85rem; border-top: 1px solid var(--line); padding-top: 18px; max-width: 72ch; }
@media (max-width: 560px) { td:first-child { white-space: normal; } }
</style>
<main>
<header>
<p class="date">4 NOVEMBER 2026 · <span class="tag open">PROPOSED, NOT BUILT</span></p>
<h1>Convergence Architecture</h1>
<p class="lead">How the City Brain grows from a sound decision layer into one system whose parts feed each other: agents, MCP tools, optimisation, mathematics, graphs, vector search and bounded self-improvement, each chosen for the question it answers best, and all of it deployable with Docker Compose on one laptop with no network.</p>
<p>It stays inside the Phase 1 contract: nothing a partner must build, every addition on the wire marked proposed, and the 23 recorded scenarios decide exactly as before with every new switch off. The specification is <code>docs/superpowers/specs/2026-11-04-convergence-architecture-design.md</code>; seven plans carry it out.</p>
</header>

<section id="context">
<h2>The Brain and everyone around it</h2>
<p>The contract fixes the two partner links: MCP tools to and from the Twin, REST to and from the Guardian. Everything new faces outwards for people and other teams, or sits behind the existing ports.</p>
<p class="legend"><span>exists today</span><span class="n">new in this design</span><span class="p">another team's layer</span><span class="g">the gate</span></p>
<div class="wide" tabindex="0" role="region" aria-label="Context diagram, scrolls sideways on a narrow screen">__CONTEXT__</div>
</section>

<section id="tech">
<h2>All the technologies together</h2>
<p>Six groups and what flows between them. The same diagram, with every logo, is on the logo page.</p>
<div class="wide" tabindex="0" role="region" aria-label="Technology map, scrolls sideways on a narrow screen">__TECH__</div>
</section>

<section id="flow">
<h2>From incident to decision</h2>
<p>Eighteen steps from a sensor reading to an action on the city, each tagged with the part of a brain it models. Amber arrows are the way out; the reflex tier acts at once and does not wait for the workspace.</p>
<div class="wide" tabindex="0" role="region" aria-label="Incident to decision flow, scrolls sideways on a narrow screen">__FLOW__</div>
</section>

<section id="layers">
<h2>Six planes and a spine</h2>
<p>Readings enter at the top of the stack and decisions leave only through the gate in plane 5. Each plane keeps what it has today and adds a few engines. The spine and the platform sit under all of them.</p>
<div class="wide" tabindex="0" role="region" aria-label="Layered architecture diagram, scrolls sideways on a narrow screen">__LAYERS__</div>
</section>

<section id="triplet">
<h2>What the triplet can build, and what we need from the partners</h2>
<p>Most protocol and hosting choices are shared, so the Brain cannot make them alone. The triplet's shared decisions are listed below, each with our proposal, an alternative we can connect to, the cost to us and a question for each partner. Nothing is agreed yet.</p>
<div class="wide" tabindex="0" role="region" aria-label="Table of shared decisions"><table>
<tr><th>Decision</th><th>Our proposal</th><th>If the partner cannot, we connect to</th><th>Status</th></tr>
<tr><td>D1 Readings, Twin to Brain</td><td>MCP, polled with a cursor</td><td>REST, MQTT, WebSocket, gRPC, a file of readings</td><td><span class="tag open">proposed</span></td></tr>
<tr><td>D2 Actions, Brain to Twin</td><td>MCP tools, signed envelope</td><td>REST, MQTT</td><td><span class="tag open">proposed</span></td></tr>
<tr><td>D3 Verdicts, Guardian</td><td>REST</td><td>The verdict inside the reading (built), MCP, gRPC</td><td><span class="tag open">proposed</span></td></tr>
<tr><td>D4 Fields</td><td>Data Dictionary plus the proposed items</td><td>Renames and units in config</td><td><span class="tag open">open</span></td></tr>
<tr><td>D5 Signing</td><td>HMAC with a key id; Ed25519 optional</td><td>A public key from the partner</td><td><span class="tag open">proposed</span></td></tr>
<tr><td>D6 Time and order</td><td>UTC, a counter per sensor, a stream id</td><td>Whatever they give, stated</td><td><span class="tag open">open</span></td></tr>
<tr><td>D7 Starting a scenario on the Twin</td><td>One call that loads and starts a scenario</td><td>A scenario file, a REST call, recorded streams</td><td><span class="tag open">open, blocks a joint run</span></td></tr>
<tr><td>D8 The shared screen</td><td>Ours, plus partner events pushed with a token</td><td>Their own screen, or only what we observe</td><td><span class="tag open">proposed</span></td></tr>
<tr><td>D9 Who runs what on 14 Nov</td><td>One compose file at the triplet root includes the three</td><td>Scripts on one router</td><td><span class="tag open">open</span></td></tr>
<tr><td>D10 Transport security</td><td>TLS from a local CA</td><td>Plain HTTP on a closed router, agreed in writing</td><td><span class="tag open">open</span></td></tr>
<tr><td>D11 Extended sensors and actuators</td><td>Required ones; extras only if the Twin offers them</td><td>Required only</td><td><span class="tag open">open</span></td></tr>
<tr><td>D12 Changing the contract</td><td>Four edits, one version string</td><td></td><td><span class="tag open">proposed</span></td></tr>
</table></div>
<h3 style="margin-top:28px">Can we build it? Measured on 4 November</h3>
<div class="wide" tabindex="0" role="region" aria-label="Table of measurements"><table>
<tr><th>Measure</th><th>Result</th></tr>
<tr><td>Size</td><td>11,612 lines of Python, 7,897 lines of tests, 2,618 lines of screen code; 707 tests, 1 known failing</td></tr>
<tr><td>Decision speed, in process</td><td>35 to 58 ms to the first action, 117 to 470 ms to the last, against a 15 s pursuit</td></tr>
<tr><td>Memory and start-up, one scenario</td><td>120 MB and 0.8 s with the stand-in embedder; <b>1,419 MB and 11.7 s with the real one</b>, because the corpus is embedded at every start</td></tr>
<tr><td>This laptop</td><td>20 cores, 15 GB, an RTX 4050 with 6 GB; Docker and Compose work</td></tr>
<tr><td>Effort left, my estimate</td><td>About 14 working days of planned work against 3 to 4 before 7 November and 10 before the demo. Everything cannot be done by 7 November, and the report and deck are not written</td></tr>
<tr><td>The cut line</td><td>Reproducibility, tokens and approval, the forged-event fix and the security invariants, Compose, and the report and deck first. The rest follows if the repository may change until 13 November</td></tr>
</table></div>
<p>Eight decision records, one per free choice, are in <code>docs/decisions/</code>. Each says who decides, what we weighed, what we measured, what it costs, what happens if it fails and what the partners must agree.</p>
</section>

<section id="repro">
<h2>Does a fixed input give the same output?</h2>
<p>Measured on 4 November before designing anything. The scripted Brain decides identically every time. The agents do not, and no hosted model can promise they will, so the design records them and replays the recording.</p>
<div class="wide" tabindex="0" role="region" aria-label="Table of reproducibility measurements"><table>
<tr><th>Measured</th><th>Result</th></tr>
<tr><td>Decisions, 5 scenarios, 5 runs each</td><td><span class="tag ok">identical</span> in every run, also across 5 processes with different hash seeds</td></tr>
<tr><td>Event stream without ids and times</td><td><span class="tag ok">identical</span> except one measured duration (<code>usage.seconds</code>, 0.0 against 0.01) in 2 of 12 runs of one scenario</td></tr>
<tr><td>Log bytes</td><td><span class="tag open">different every run</span>: a random id per event and the wall clock</td></tr>
<tr><td>The agents' prompt</td><td><span class="tag open">differs</span> by the wall-clock time of the incident</td></tr>
<tr><td>Real model, same prompt, temperature 0</td><td><span class="tag open">5 different answers in 5 calls</span>; with a seed, 4 different in 5</td></tr>
<tr><td>Real team on the earlier b2 (now t14), 26 Oct, 5 trials</td><td>3 distinct plans, agreement 0.75, all 5 passed the checks</td></tr>
<tr><td>Can a log be replayed?</td><td><span class="tag open">no</span>: it keeps a summary of each reading, not the reading</td></tr>
</table></div>
<h3 style="margin-top:28px">What the Brain claims, level by level</h3>
<div class="wide" tabindex="0" role="region" aria-label="Table of reproducibility claims"><table>
<tr><th>Level</th><th>Claim</th><th>After plan P0</th></tr>
<tr><td>Decisions</td><td>Same input and settings, same actions and refusals</td><td>Tested on every scenario</td></tr>
<tr><td>Event stream</td><td>Same events, ignoring ids and times</td><td>Durations move out of event data; a test lists any field that varies</td></tr>
<tr><td>Bytes</td><td>Same log and same hash-chain head</td><td>With an injected clock and counter ids</td></tr>
<tr><td>Prompt</td><td>The agents see the same input</td><td>Times in a brief become seconds since the incident</td></tr>
<tr><td>Agents</td><td>Same words from a hosted model</td><td>Not promised. Replayed from a cassette: identical. Live: variation measured and bounded by the verifiers and the gate</td></tr>
<tr><td>Environment</td><td>Same versions, models and tuned settings</td><td>A fingerprint in the first event of every run</td></tr>
</table></div>
<p>Two commands carry it: <code>brain repro</code> runs a scenario several times and prints each level, and <code>brain replay</code> takes a run's input journal and checks that the Brain makes the same decisions. On stage, a real-model plan recorded beforehand plays offline and identically, labelled as a recording.</p>
</section>

<section id="brain">
<h2>The planes are brain-inspired regions</h2>
<p>The six planes are the eleven regions the canopy draws inside its glass brain, grouped by what they do. Each models a function of a brain as engineering, and each says where the analogy stops. The agents live in one region only, the team; every other region is code that checks them. Nothing claims the Brain is conscious.</p>
<div class="wide" tabindex="0" role="region" aria-label="Side view of the glass brain, scrolls sideways on a narrow screen">__BRAINVIEW__</div>
<p>Steel dots are code, the violet dot is the team, where the agents live, and the amber dot is the gate, the only way out.</p>
<div class="wide" tabindex="0" role="region" aria-label="Table of planes, regions and analogues" style="margin-top:16px"><table>
<tr><th>Plane</th><th>Regions on the canopy</th><th>Brain analogue</th><th>New engines, and their analogue</th><th>Where the analogy stops</th></tr>
__PLANEROWS__
</table></div>
<p>Region by region, with sources, parameters and how each is built: <code>docs/BRAIN-MAPPING.md</code> and the Brain Map page.</p>
</section>

<section id="phase1">
<h2>The Phase 1 rules, checked against the repository</h2>
<p>The "Required" rules make the system testable and the work visible. Each was checked on 4 November by running the commands in <code>docs/PHASE1-COMPLIANCE.md</code>. The PDF calls them three simple rules and lists four; all four count.</p>
<div class="wide" tabindex="0" role="region" aria-label="Table of the Phase 1 rules"><table>
<tr><th>Rule</th><th>What it asks</th><th>Where we are</th><th>Fix</th></tr>
<tr><td>R1 Runs alone</td><td>Mocks of the two other layers; a one-page Interface Card with an example of each message, how to repoint it, how it authenticates</td><td><span class="tag ok">met</span> mocks and README. <span class="tag ok">met</span> the card is 62 lines with an example of every message, how to repoint it and how it authenticates (closed 4 November)</td><td><code>tests/test_phase1_requirements.py</code> keeps it true</td></tr>
<tr><td>R2 One trigger, one log</td><td>One command or button per scenario; a log file per run, stored in the repository</td><td><span class="tag ok">met</span> command, button and a hash-chained log per run. <span class="tag open">gap</span> no trigger script per scenario; 141 logs and no canonical one for each scenario</td><td>Generated trigger scripts; one canonical log per scenario (plan 5)</td></tr>
<tr><td>R3 Live timeline</td><td>Reading, verdict, decision, action across three layers with timestamps</td><td><span class="tag ok">met</span> on the Brain's own events. The RTX 4050 and a real partner are unchecked</td><td>Namespace rule so a partner cannot forge rows (plan 6)</td></tr>
<tr><td>R4 Coordination</td><td>How the teams coordinated, a partner failure or change handled, proof of a successful joint run</td><td><span class="tag open">gap</span> the Brain has never run with the real Twin or Guardian</td><td>The charter sent to the partners; a first joint run is a milestone (plan 5)</td></tr>
</table></div>
<p>The layout also puts <code>scenarios/</code>, <code>logs/</code>, <code>docker-compose.yml</code>, <code>INTEGRATION.md</code> and <code>TESTBOOK.md</code> at the triplet root, shared between teams (decision D13). The report and the pitch deck, due 7 November, are not written.</p>
</section>

<section id="choices">
<h2>The eight free choices, and how each is defended</h2>
<p>The Phase 1 text leaves these free: architecture, languages, protocols, hosting, databases, AI and ML methods, the user interface and the scenarios. "Choose what your triplet can build and defend." Each row names the reason, what we rejected and what in the repository shows it holds.</p>
<div class="wide" tabindex="0" role="region" aria-label="Table of the free choices"><table>
<tr><th>Choice</th><th>We chose</th><th>Because</th><th>We rejected</th><th>Shown by</th></tr>
<tr><td>Architecture</td><td>Ports and adapters round a decision core; an event timeline; one gate</td><td>Partner I/O is separate from logic, which is scored</td><td>Service per region; partner calls inside rules</td><td><code>tests/test_layering.py</code>: logic never imports an adapter; a test that only the gate calls the Twin</td></tr>
<tr><td>Language</td><td>Python 3.12 with types; plain JavaScript for the screen</td><td>LangGraph, OR-Tools, the MCP SDK and the vector and graph clients are here first</td><td>Go, Rust, TypeScript, Java</td><td>Lock file; type checks on contracts and gate</td></tr>
<tr><td>Protocols</td><td>MCP, REST, SSE with CloudEvents, OTLP</td><td>One per link, for that link's job (next section)</td><td>MQTT, WebSocket, gRPC, Kafka as defaults</td><td>An MQTT adapter that decides as MCP does</td></tr>
<tr><td>Hosting</td><td>One laptop first; Compose</td><td>No Wi-Fi in the hall, nothing installed on stage</td><td>Cloud only; serverless</td><td>Hall kit; make full</td></tr>
<tr><td>Databases</td><td>Memory graph, Neo4j, Qdrant, SQLite, a hash-chained log</td><td>Each answers a question the others answer badly</td><td>One database for everything</td><td>rag-eval rows; degraded-mode scenarios</td></tr>
<tr><td>AI and ML</td><td>Rules, statistics, optimisation, retrieval, checked agents, bounded self-improvement</td><td>Each method for the question it answers best, measured</td><td>Trained networks, reinforcement learning, a fine-tuned model: no data yet, and an opaque model cannot be checked by the gate</td><td>forward-bench, optimise-bench, reliability</td></tr>
<tr><td>Interface</td><td>One static page served by the Brain, one vendored library, SSE</td><td>Works offline on a projector; cause and effect in ten seconds</td><td>A framework and build chain</td><td>A content-security policy; screenshots</td></tr>
<tr><td>Scenarios</td><td>A Test Book of 23 growing to 38, each with expected output per layer</td><td>The rule: all three layers and every interaction</td><td>Scenarios copied from the brief</td><td>A coverage test per required interaction</td></tr>
</table></div>
</section>

<section id="boundary">
<h2>Where the line falls between logic and partners</h2>
<p>Everything outside the two ports can be replaced: a new Twin or Guardian means a new adapter class or an edited <code>config/partners.yaml</code>, and the logic cannot tell the difference. <code>tests/test_layering.py</code> fails if logic imports an adapter, or an adapter imports logic. A message that is wrong is refused on entry with a stated code and reason; the report lists each one.</p>
<div class="wide" tabindex="0" role="region" aria-label="Boundary diagram, scrolls sideways on a narrow screen">__BOUNDARY__</div>
</section>

<section id="protocols">
<h2>Protocols, link by link</h2>
<p>One protocol per link, chosen for that link's job. The ports make each one replaceable by a single adapter class.</p>
<div class="wide" tabindex="0" role="region" aria-label="Table of protocol decisions"><table>
<tr><th>Link</th><th>Chosen</th><th>Why</th><th>Looked at, and why not the default</th></tr>
<tr><td>Twin and Brain</td><td>MCP tools. Readings polled with a cursor; actions are tools</td><td>One connection both ways. Tools describe themselves, so the gate learns what the Twin can do. The agent standard. A cursor gives backpressure and restart without loss</td><td><b>MQTT</b>: a broker on stage, no schema, no single exchange for a call and its result (an adapter is built to prove the separation). <b>WebSocket</b>: no schema or replay. <b>gRPC</b>: toolchain on both teams, opaque in logs. <b>Kafka</b>: infrastructure</td></tr>
<tr><td>Brain and Guardian</td><td>REST</td><td>One question, one answer, with a deadline. Any team can build it in an afternoon and read it with curl</td><td><b>MCP</b>: not an agent's tool. <b>gRPC</b>: as above</td></tr>
<tr><td>Brain to viewers</td><td>Server-Sent Events carrying CloudEvents 1.0</td><td>One way, plain HTTP, reconnects by itself, replays then follows. Actions go the other way by REST</td><td><b>WebSocket</b>: two-way not needed. <b>Polling</b>: wasteful, no order</td></tr>
<tr><td>Other agents to Brain</td><td>MCP and an agent card</td><td>The tool standard for agents; read-only, so it cannot widen the gate</td><td><b>REST only</b>: no tool discovery</td></tr>
<tr><td>Telemetry</td><td>OTLP and Prometheus</td><td>Vendor-neutral; every tool reads them</td><td></td></tr>
<tr><td>Formats</td><td>JSON; JSON Schema 2020-12; OpenAPI 3.1; AsyncAPI; W3C PROV-JSON; canonical JSON for signatures</td><td>Standard and well known, which the jury looks for</td><td></td></tr>
</table></div>
</section>

<section id="security">
<h2>Security, enforced in layers and by tests</h2>
<p>Six layers, each assuming the one outside it can fail: network (TLS, network rules), edge (scoped short-lived tokens, size and rate limits), message (signature with a key id, replay check, schema), decision (code checks the agents), action (the gate, a person for high impact), audit (a signed, chained, replayable record). Security that depends on remembering is not enforced, so the build fails if an invariant breaks.</p>
<div class="wide" tabindex="0" role="region" aria-label="Table of audit findings"><table>
<tr><th>Finding from probing the code on 4 Nov</th><th>Why it matters</th><th>Fixed by</th></tr>
<tr><td><span class="tag open">F1</span> A forged timeline event pushed as the Twin is accepted and streamed. The screen reads the event type and not its source, and a forged session reset would clear it</td><td>Anyone who can reach the port can fake a decision or wipe the jury's screen</td><td>A partner may push only inside its own namespace; <code>brain.*</code> is reserved; the screen checks the source (plan 6)</td></tr>
<tr><td><span class="tag open">F2</span> The push took a 5 MB body; no size or rate limit</td><td>A flood or a very large body</td><td>Limits and scoped tokens (plan 1)</td></tr>
<tr><td><span class="tag open">F3</span> Every read endpoint is open</td><td>Fine on loopback; not off the machine</td><td>Scopes, required off loopback (plan 1)</td></tr>
<tr><td><span class="tag open">F4</span> No TLS on any link</td><td>Traffic readable and changeable in transit</td><td>TLS and optional mutual TLS (plan 6)</td></tr>
<tr><td><span class="tag open">F5</span> One shared HMAC secret, no key id, no rotation, no time or nonce on actuator calls</td><td>A leaked key cannot be rotated safely; a call could be replayed</td><td>Key ids, a key ring, optional Ed25519, time and nonce (plan 6)</td></tr>
<tr><td><span class="tag open">F7</span> "Only the gate calls the Twin" is true but no test says so</td><td>A claim that can silently stop being true</td><td>An AST invariant test (plan 6)</td></tr>
<tr><td><span class="tag open">F9</span> The log's hash chain is not anchored</td><td>Someone with disk access could rewrite all of it consistently</td><td>A signed chain head, optionally copied to a witness (plan 6)</td></tr>
<tr><td><span class="tag ok">checked</span> Path traversal attempts return 404. HMAC comparison is constant time. No eval, pickle, shell or disabled certificate checks. Cypher values are parameters. The default bind is loopback</td><td></td><td>Kept as invariants</td></tr>
</table></div>
<p>Scenarios grow to cover the Phase 1 interaction rule where it is thin today: a flood of readings from one device, a sensor that goes silent, the Twin going away mid-run, a real incident during an attack, a forged push, key rotation, and the same city over MQTT.</p>
</section>

<section id="tools">
<h2>One question, one engine</h2>
<p>A tool earns its place by the question it answers best. Every row has a fallback that is today's behaviour, and a command that proves it. A feature that does not beat what it replaces is reported as a null result and left off, as GraphRAG already was.</p>
<div class="wide" tabindex="0" role="region" aria-label="Table of questions and engines"><table>
<tr><th>Question</th><th>Engine</th><th>If it is down</th><th>Proof</th></tr>
<tr><td>Is this reading believable?</td><td>Forward models, Guardian verdict, Kalman tracker</td><td>Rule tier keeps running</td><td class="num">forward-bench</td></tr>
<tr><td>How sure are we the incident is real?</td><td>Bayesian log-odds over independent witnesses</td><td>Belief not shown</td><td class="num">reliability table</td></tr>
<tr><td>What is connected, and what fails if this fails?</td><td>Neo4j, networkx, cascade analysis</td><td>Memory graph</td><td class="num">every cited id resolves</td></tr>
<tr><td>What do we know about this?</td><td>Qdrant: dense, BM25 and filters fused on the server</td><td>In-memory index</td><td class="num">rag-eval, all backends</td></tr>
<tr><td>Which units go to which incident?</td><td>OR-Tools min-cost flow</td><td>Nearest station</td><td class="num">optimise-bench</td></tr>
<tr><td>Where do we place a perimeter in time?</td><td>OR-Tools CP-SAT</td><td>The Tactician's own choice</td><td class="num">certificate, Monte-Carlo</td></tr>
<tr><td>Which load do we shed?</td><td>CP-SAT knapsack weighted by cascade impact</td><td>Hold for a person</td><td class="num">brute-force check</td></tr>
<tr><td>How soon does the water overflow?</td><td>Kalman filter, level and rate</td><td>Static threshold</td><td class="num">forward-bench ramps</td></tr>
<tr><td>What path clears the way for an ambulance?</td><td>Time-dependent shortest path, then signals</td><td>No corridor</td><td class="num">unit tests</td></tr>
<tr><td>What is the plan?</td><td>Agent team on LangGraph, bounded by the solver</td><td>Scripted team, solver</td><td class="num">plan agreement, gap</td></tr>
<tr><td>Is it allowed?</td><td>The gate. Code, never a model</td><td>It cannot be absent</td><td class="num">t12 to t15, red team</td></tr>
<tr><td>Who may approve a valve or grid cut?</td><td>LangGraph interrupt and an HMAC-signed approval</td><td>The action stays held</td><td class="num">tampered approval refused (tests)</td></tr>
<tr><td>Why did it do that?</td><td>Explanation from the log, PROV export, signed bundle</td><td>Same, from the log alone</td><td class="num">counterfactuals on the gate</td></tr>
<tr><td>How do we improve safely?</td><td>Sleep, Academy, one audited improvement cycle</td><td>Off</td><td class="num">before and after on held-out seeds</td></tr>
<tr><td>How does a stranger plug in?</td><td>Ports, onboarding mapper, conformance kit, MCP server, agent card</td><td>Not applicable</td><td class="num">kit passes ours, fails a broken mock</td></tr>
<tr><td>How do we run it anywhere?</td><td>Images, Compose, OpenTelemetry</td><td>Compose on one laptop</td><td class="num">make full</td></tr>
</table></div>
</section>

<section id="planner">
<h2>The fast path proves, the slow path improves</h2>
<p>The solver answers in milliseconds with no network, so it is always there. The agent team may take seconds and may be absent. Both pass through the same checks; the better feasible plan stands, and the gap is recorded. High-impact actions pause for a signed approval, and a restart resumes the wait.</p>
<div class="wide" tabindex="0" role="region" aria-label="Planning supervisor diagram, scrolls sideways on a narrow screen">__PLANNER__</div>
</section>

<section id="memory">
<h2>Five stores, five questions</h2>
<p>Each store is there for something the others do badly. The decision path reads memory only, so no database outage can slow a decision.</p>
<div class="wide" tabindex="0" role="region" aria-label="Table of stores"><table>
<tr><th>Store</th><th>Holds</th><th>Written by</th><th>Read by</th><th>If it is down</th></tr>
<tr><td>In-memory graph (networkx)</td><td>Zones, facilities, incidents, evidence, verdicts</td><td>Perception, triage</td><td>Gate, engines, agents</td><td class="num">cannot be down: it is the process</td></tr>
<tr><td>Neo4j 5.26</td><td>The same graph with provenance; criticality, communities, cascade weight</td><td>Write-behind mirror, analytics</td><td>Cypher, explanations, screen context</td><td class="num">memory graph; one degraded event</td></tr>
<tr><td>Qdrant</td><td>Knowledge vectors (dense, sparse) and episode vectors</td><td>Start-up sync, sleep</td><td>Agents, partners over MCP</td><td class="num">in-memory index; one degraded event</td></tr>
<tr><td>JSONL hash chain</td><td>Every timeline event</td><td>All engines</td><td>Screen, explain, verify-log, PROV</td><td class="num">not optional</td></tr>
<tr><td>SQLite</td><td>Working state, plan checkpoints, pending and used approvals</td><td>Runtime, supervisor</td><td>Restart, replay, approval check</td><td class="num">Brain refuses high-impact actions</td></tr>
</table></div>
</section>

<section id="trace">
<h2>One flood, through every engine</h2>
<p>Shown in scenario <code>t15</code>. It shows the interconnection in one pass: the same trace id follows the reading through all of this.</p>
<ol class="flow">
<li><b>A water-level reading arrives, signed.</b> Perception checks the contract, the signature and the replay counter.</li>
<li><b>The Guardian trusts it and the forward model agrees.</b> The Kalman tracker reports the rise rate and a time to the flood threshold with an interval.</li>
<li><b>Triage opens a flood.</b> Belief fuses the independent witnesses. The workspace lights it without taking a slot.</li>
<li><b>The utilities rule proposes an alert and a valve closure.</b> The alert passes the gate. The valve call is held: it needs human approval.</li>
<li><b>The supervisor records an approval request</b> and pauses at the interrupt. The screen shows a pending strip with the explanation: margins, lead time, what would change the decision.</li>
<li><b>The presenter clicks Approve.</b> The signed approval is bound to the valve call's parameters and can be used once. The gate re-checks everything and sends the call. The Twin closes the valve.</li>
<li><b>A tampered approval is tried and refused</b> with the reason hash mismatch. The red-team suite runs the same attack.</li>
<li><b>The Why panel replays the thought</b> through the glass brain; the PROV export and the signed bundle let a third party verify the chain.</li>
</ol>
</section>

<section id="deploy">
<h2>Runs on one laptop, offline</h2>
<p>The chart is cloud-neutral and uses plain templates, so it installs with no registry. Pointing the Brain at a different partner is a ConfigMap edit. On stage the default is Compose with the hall kit, because the hall has no Wi-Fi and nothing may be installed.</p>
<div class="wide" tabindex="0" role="region" aria-label="Deployment diagram, scrolls sideways on a narrow screen">__DEPLOY__</div>
</section>

<section id="loop">
<h2>Self-improvement with a fence round it</h2>
<p>A solver's optimality gap is a learning signal that is not the outcome of a dispatch, so the project rule holds. The loop improves a listed set of numbers on held-out stories and promotes only what breaks nothing. If no proposal passes, the report says so.</p>
<div class="wide" tabindex="0" role="region" aria-label="Improvement loop diagram, scrolls sideways on a narrow screen">__LOOP__</div>
</section>

<section id="plans">
<h2>Seven plans, foundation first</h2>
<div class="wide" tabindex="0" role="region" aria-label="Table of plans"><table>
<tr><th>Plan</th><th>Delivers</th><th>Depends on</th><th>Cut class</th></tr>
<tr><td>P0 Reproducibility</td><td>brain repro, injected clock and ids, input journal, agent cassette, brain replay, environment fingerprint</td><td>none; runs first</td><td><span class="tag ok">must</span></td></tr>
<tr><td>P1 Contract and trust</td><td>Tool registry, Brain MCP server, agent card, scoped tokens, signed approval, conformance kit, onboarding mapper, red team, one-page Interface Card</td><td>none</td><td><span class="tag ok">must</span></td></tr>
<tr><td>P6 Protocols and security</td><td>Push boundary and screen check, security invariants as tests, key ids and rotation, short-lived tokens, TLS, an MQTT adapter, a signed chain head, a security report</td><td>P1</td><td><span class="tag ok">must</span> boundary, invariants, scenarios · <span class="tag open">should</span> keys, TLS, MQTT</td></tr>
<tr><td>P2 Decision engines</td><td>OR-Tools dispatch, perimeter and shedding; Kalman, belief, corridor; the LangGraph supervisor; optimise-bench</td><td>P1 registry and approval</td><td><span class="tag ok">must</span> core · <span class="tag open">should</span> depth</td></tr>
<tr><td>P3 Memory, graph, learning</td><td>Qdrant backend measured against the others, graph analytics, PROV, similar stories, improvement cycle</td><td>P2 benchmarks</td><td><span class="tag open">should</span></td></tr>
<tr><td>P4 Platform</td><td>Images, Compose profiles, telemetry, hall kit, CI file</td><td>P1 auth; P3 stores for the full stack</td><td><span class="tag ok">must</span> Compose</td></tr>
<tr><td>P5 Evidence and narrative</td><td>Decision records, brain bench, print diagrams, report and deck outlines, demo script, rehearsals</td><td>all, from day one</td><td><span class="tag ok">must</span></td></tr>
</table></div>
<p>Submission is Saturday 7 November. The report and the deck are not written yet and are a quarter or more of what is submitted, so P5 runs beside the engineering and not after it.</p>
</section>

<footer>The Brain is brain-inspired: it models functions such as attention, prediction error and sleep. Nothing here claims more. Numbers in this page are measured by commands in the repository once the plans are built; until then they are targets and say so.</footer>
</main>
"""


def main() -> None:
    page = (PAGE.replace("__TECH__", tech_map()).replace("__FLOW__", incident_flow()).replace("__BRAINVIEW__", side_view()).replace("__PLANEROWS__", PLANE_ROWS).replace("__CONTEXT__", context()).replace("__BOUNDARY__", boundary()).replace("__LAYERS__", layers()).replace("__PLANNER__", planner())
            .replace("__DEPLOY__", deployment()).replace("__LOOP__", loop()))
    OUT.write_text(page)
    print(f"wrote {OUT} ({len(page) // 1024} KB)")


if __name__ == "__main__":
    main()
