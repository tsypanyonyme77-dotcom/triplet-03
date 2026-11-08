"""Writes docs/architecture-logos.html: the Convergence architecture as logo diagrams with a few words on each node.

    uv run python docs/diagrams/logo_architecture.py

Logos live in docs/diagrams/logos/ (see the README there) and are embedded in the page as data URIs, because a published
artifact may not load images from other hosts and the hall has no network. A card with the accent fill is proposed; a plain
card is built today.
"""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brain_map import side_view  # noqa: E402  the same drawing as the brain map page

HERE = Path(__file__).resolve().parent
LOGOS = HERE / "logos"
OUT = HERE.parent / "architecture-logos.html"

# Brand colour for the single-path Simple Icons files, which ship with no fill. Dark brand colours are kept: the tile behind a logo is white in both themes.
BRAND = {
    "python": "3776AB", "fastapi": "009688", "neo4j": "4581C3", "qdrant": "DC244C", "docker": "2496ED", "prometheus": "E6522C", "grafana": "F46800", "opentelemetry": "425CC7", "jaeger": "3AAFC2", "sqlite": "003B57",
    "langgraph": "1C3C3C", "langchain": "1C3C3C", "pydantic": "E92063", "numpy": "013243", "anthropic": "191919", "huggingface": "E8B200",
    "githubactions": "2088FF", "modelcontextprotocol": "111111", "uv": "DE5FE9", "pytest": "0A9EDC", "threedotjs": "111111",
    "mqtt": "660066", "apachekafka": "231F20", "openapiinitiative": "6BA539", "eclipsemosquitto": "3C5280", "jsonwebtokens": "111111", "openssl": "721412",
}
SIZES = {"networkx": (96, 101), "groq": (40, 15), "grpc": (366, 157), "cloudevents": (366, 246)}  # width, height of the files that are not square

GLYPHS = {
    "city": '<path d="M6 42V22h10v20M16 42V10h12v32M28 42V26h10v16M4 42h40"/>',
    "shield": '<path d="M24 5l15 5v12c0 9-6 16-15 20-9-4-15-11-15-20V10z"/><path d="M17 24l5 5 9-10"/>',
    "brain": '<circle cx="24" cy="24" r="5"/><circle cx="9" cy="13" r="3"/><circle cx="39" cy="13" r="3"/><circle cx="8" cy="34" r="3"/><circle cx="40" cy="34" r="3"/><circle cx="24" cy="6" r="3"/>'
             '<path d="M20 21L11 15M28 21l9-6M20 28l-9 5M28 28l9 5M24 19V9"/>',
    "lock": '<rect x="11" y="21" width="26" height="20" rx="3"/><path d="M16 21v-6a8 8 0 0 1 16 0v6"/><circle cx="24" cy="31" r="2"/>',
    "person": '<circle cx="24" cy="15" r="7"/><path d="M9 42c0-9 7-14 15-14s15 5 15 14"/>',
    "monitor": '<rect x="5" y="9" width="38" height="24" rx="3"/><path d="M17 41h14M24 33v8"/>',
    "moon": '<path d="M35 31A16 16 0 0 1 17 9a16 16 0 1 0 18 22z"/>',
    "dial": '<path d="M7 35a17 17 0 1 1 34 0"/><path d="M24 35l9-13"/><circle cx="24" cy="35" r="2.5"/>',
    "loop": '<path d="M38 20a14 14 0 0 0-26-4"/><path d="M12 8v8h8"/><path d="M10 28a14 14 0 0 0 26 4"/><path d="M36 40v-8h-8"/>',
    "file": '<path d="M12 5h17l9 9v29H12z"/><path d="M29 5v9h9"/><path d="M18 24h14M18 31h14M18 38h8"/>',
    "box": '<path d="M24 5l17 8v22l-17 8-17-8V13z"/><path d="M7 13l17 8 17-8M24 21v22"/>',
    "eye": '<path d="M3 24c6-10 14-14 21-14s15 4 21 14c-6 10-14 14-21 14S9 34 3 24z"/><circle cx="24" cy="24" r="6"/>',
    "alert": '<path d="M24 6l19 34H5z"/><path d="M24 18v10M24 33v2"/>',
    "scale": '<path d="M24 8v32M12 40h24M10 14h28"/><path d="M10 14l-5 12h10zM38 14l-5 12h10z"/>',
    "ws": '<path d="M6 17h30l-7-7M42 31H12l7 7"/>',
    "sse": '<path d="M5 24h24M21 14l10 10-10 10"/><path d="M38 12v24"/>',
    "poll": '<path d="M24 8a16 16 0 1 0 16 16"/><path d="M24 2v12l8-6z"/>',
    "agents": '<circle cx="24" cy="12" r="5"/><circle cx="10" cy="34" r="5"/><circle cx="38" cy="34" r="5"/><path d="M21 16l-8 14M27 16l8 14M15 36h18"/>',
}


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def logo_uri(name: str) -> tuple[str, float]:
    """A data URI for a logo file and its width over its height."""
    if (LOGOS / f"{name}.png").exists():
        return "data:image/png;base64," + base64.b64encode((LOGOS / f"{name}.png").read_bytes()).decode(), 1.0
    svg = (LOGOS / f"{name}.svg").read_text()
    if name in BRAND:
        svg = re.sub(r"<svg ", f'<svg fill="#{BRAND[name]}" ', svg, count=1)
    if name == "networkx":  # the file is the full banner with no viewBox and Inkscape-only lettering: keep the node mark on its left
        svg = re.sub(r'width="[\d.]+"\s+height="[\d.]+"', 'width="96" height="101" viewBox="0 0 96 101"', svg, count=1)
    w, h = SIZES.get(name, (24, 24))
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode(), w / h


def glyph(name: str, cx: float, cy: float, size: float = 44) -> str:
    k = size / 48
    return f'<g class="glyph" transform="translate({cx - size / 2:.1f} {cy - size / 2:.1f}) scale({k:.3f})">{GLYPHS[name]}</g>'


class Card:
    W, H, TILE = 176, 132, 62

    def __init__(self, x: int, y: int, w: int | None = None) -> None:
        self.x, self.y, self.w, self.h = x, y, w or self.W, self.H

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

    def card(self, x: int, y: int, icons: list[str], title: str, caption: str = "", cls: str = "", w: int | None = None, tag: str = "") -> Card:
        card = Card(x, y, w)
        if tag:
            card.h += 20
        out = [f'<rect class="card {cls}" x="{x}" y="{y}" width="{card.w}" height="{card.h}" rx="10"/>']
        parts, widths = [], []
        for name in icons:
            if name in GLYPHS:
                widths.append(40)
                parts.append(("glyph", name, 40))
            else:
                uri, aspect = logo_uri(name)
                width = min(112, max(34, round(34 * aspect)))
                widths.append(width)
                parts.append(("logo", uri, width))
        tile_w = min(card.w - 24, sum(widths) + 14 * (len(icons) - 1) + 28)
        tx, ty = card.cx - tile_w // 2, y + 12
        out.append(f'<rect class="tile" x="{tx}" y="{ty}" width="{tile_w}" height="{card.TILE}" rx="8"/>')
        cursor = card.cx - (sum(widths) + 14 * (len(icons) - 1)) // 2
        for (kind, ref, width) in parts:
            if kind == "glyph":
                out.append(glyph(ref, cursor + width / 2, ty + card.TILE / 2, 38))
            else:
                out.append(f'<image href="{ref}" x="{cursor}" y="{ty + card.TILE / 2 - 17}" width="{width}" height="34" preserveAspectRatio="xMidYMid meet"/>')
            cursor += width + 14
        out.append(f'<text class="t" x="{card.cx}" y="{y + 99}" text-anchor="middle">{esc(title)}</text>')
        if caption:
            out.append(f'<text class="s" x="{card.cx}" y="{y + 118}" text-anchor="middle">{esc(caption)}</text>')
        if tag:
            out.append(f'<text class="an" x="{card.cx}" y="{y + 138}" text-anchor="middle">{esc(tag)}</text>')
        self.shapes.append("<g>" + "".join(out) + "</g>")
        self.low = max(self.low, card.bottom)
        return card

    def mini(self, x: int, y: int, icon: str, name: str, why: str, built: bool = False) -> None:
        """A small tile for an option we looked at: logo, name, and the reason in a few words."""
        out = [f'<rect class="card {"new" if built else ""}" x="{x}" y="{y}" width="124" height="104" rx="8"/>',
               f'<rect class="tile" x="{x + 30}" y="{y + 8}" width="64" height="40" rx="6"/>']
        if icon in GLYPHS:
            out.append(glyph(icon, x + 62, y + 28, 26))
        else:
            uri, aspect = logo_uri(icon)
            width = min(52, max(22, round(24 * aspect)))
            out.append(f'<image href="{uri}" x="{x + 62 - width / 2}" y="{y + 16}" width="{width}" height="24" preserveAspectRatio="xMidYMid meet"/>')
        out.append(f'<text class="t" x="{x + 62}" y="{y + 66}" text-anchor="middle" style="font-size:13px">{esc(name)}</text>')
        for i, row in enumerate(why.split("\n")):
            out.append(f'<text class="s" x="{x + 62}" y="{y + 82 + 13 * i}" text-anchor="middle" style="font-size:11px">{esc(row)}</text>')
        self.shapes.append("<g>" + "".join(out) + "</g>")
        self.low = max(self.low, y + 104)

    def arrow(self, d: str, cls: str = "", both: bool = False) -> None:
        marker = "headember" if cls == "ember" else "head"
        start = f' marker-start="url(#{marker})"' if both else ""
        self.shapes.append(f'<path class="arrow {cls}" d="{d}"{start} marker-end="url(#{marker})"/>')

    def label(self, x: int, y: int, text: str, anchor: str = "middle", cls: str = "k") -> None:
        for i, row in enumerate(text.split("\n")):
            self.shapes.append(f'<text class="{cls}" x="{x}" y="{y + 13 * i}" text-anchor="{anchor}">{esc(row)}</text>')

    def frame(self, x: int, y: int, w: int, h: int, label: str = "") -> None:
        self.shapes.append(f'<rect class="frame" x="{x}" y="{y}" width="{w}" height="{h}" rx="12"/>')
        if label:
            self.shapes.append(f'<text class="k" x="{x + 16}" y="{y + 22}">{esc(label)}</text>')
        self.low = max(self.low, y + h)

    def svg(self) -> str:
        h = self.low + 16
        defs = ('<defs><marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="headfill"/></marker>'
                '<marker id="headember" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="headember"/></marker></defs>')
        return f'<svg role="img" aria-label="{esc(self.alt)}" viewBox="0 0 {self.width} {h}" width="{self.width}" height="{h}">{defs}{"".join(self.shapes)}</svg>'


def big_picture() -> str:
    c = Canvas(1240, "The Twin feeds both the Brain and the Guardian. The Brain asks the Guardian for its verdict on each reading over REST, and every action leaves through the gate.")
    others = c.card(532, 8, ["modelcontextprotocol"], "Other teams", "call our tools", "new")
    twin = c.card(30, 180, ["city"], "Twin", "the city engine", "partner")
    brain = c.card(500, 180, ["brain", "python", "langgraph", "fastapi"], "City Brain", "Python, LangGraph, FastAPI", "", 240)
    guardian = c.card(1034, 180, ["shield"], "Guardian", "trust verdicts", "partner")
    screen = c.card(300, 372, ["threedotjs"], "Screen", "live brain and city")
    gate = c.card(532, 372, ["lock"], "Gate", "the only way out", "gate")
    ops = c.card(764, 372, ["grafana", "jaeger"], "Operators", "metrics and traces", "new")
    c.arrow(f"M{twin.right} 232 H{brain.x}")
    c.label(285, 222, "readings · MCP")
    # The Twin feeds the Guardian too; the Brain asks for the verdict on the same signed reading by sensor and sequence number.
    c.arrow(f"M{twin.x + 40} {twin.bottom} V560 H{guardian.cx} V{guardian.bottom}")
    c.label(900, 552, "readings, pushed · REST /v1/readings")
    c.arrow(f"M{brain.right} 218 H{guardian.x}")
    c.label(887, 208, "ask: sensor + seq no · REST")
    c.arrow(f"M{guardian.x} 254 H{brain.right}")
    c.label(887, 272, "signed verdict · REST")
    c.arrow(f"M{others.cx} {others.bottom} V{brain.y}")
    c.label(others.cx + 14, 166, "MCP tools", "start")
    c.arrow(f"M{brain.cx} {brain.bottom} V{gate.y}")
    c.arrow(f"M{brain.x + 20} {brain.bottom} V340 H{screen.cx} V{screen.y}")
    c.label(screen.cx - 8, 330, "live feed", "end")
    c.arrow(f"M{brain.right - 20} {brain.bottom} V340 H{ops.cx} V{ops.y}")
    c.arrow(f"M{gate.cx} {gate.bottom} V528 H{twin.cx} V{twin.bottom}", "ember")
    c.label(369, 520, "signed calls · 4 kinds audited by the Guardian", "middle")
    c.low = max(c.low, 566)
    return c.svg()


ANALOGUE = {"Connect": "sensory input", "Sense": "thalamus,\ncerebellum, amygdala", "Understand": "hippocampus,\nsemantic memory",
            "Decide": "workspace, habits,\nprefrontal team", "Protect": "basal ganglia", "Learn": "sleep and replay",
            "Reproduce": "not biological", "Observe": "not biological", "Run": "not biological"}


def stack() -> str:
    c = Canvas(1240, "The stack in nine rows: connect, sense, understand, decide, protect, learn, reproduce, observe and run, each with the technologies it uses.")
    rows = [
        ("Connect", [(["modelcontextprotocol"], "Tool server", "partners call it", "new"), (["fastapi"], "API and feed", "REST and live events", ""),
                     (["pydantic"], "Contracts", "checked on entry", "")]),
        ("Sense", [(["eye"], "Perception", "signed and checked", ""), (["numpy"], "Forward models", "expect each sensor", ""),
                   (["numpy"], "Flood tracker", "time to overflow", "new")]),
        ("Understand", [(["networkx", "neo4j"], "City graph", "what connects", ""), (["qdrant", "huggingface"], "Knowledge", "what we know", "new"),
                        (["file"], "Why trail", "every step explained", "")]),
        ("Decide", [(["python", "langgraph"], "Reflex graph", "LangGraph, no model", ""), (["ortools"], "Allocator", "best use of units", "new"),
                    (["langgraph"], "LangGraph planner", "plans, pauses, resumes", "new"), (["langchain", "groq"], "Agent team", "LangChain models", "")]),
        ("Protect", [(["lock"], "Gate", "the only way out", "gate"), (["person"], "Approval", "a person says yes", "new"),
                     (["shield"], "Access", "scoped tokens", "new")]),
        ("Learn", [(["moon"], "Sleep", "stories to reflexes", ""), (["dial"], "Academy", "tunes a short list", ""),
                   (["loop"], "Improve", "measured, then audited", "new")]),
        ("Reproduce", [(["file"], "Journal", "every input kept", "new"), (["loop"], "Replay", "same input, same output", "new"),
                       (["langchain", "groq"], "Agent cassette", "model calls on tape", "new"), (["uv", "docker"], "Pinned build", "locked versions", "new")]),
        ("Observe", [(["opentelemetry"], "Traces", "one per reading", "new"), (["prometheus"], "Metrics", "gate, solver, search", "new"),
                     (["grafana"], "Dashboards", "for the jury", "new"), (["jaeger"], "Trace view", "follow one reading", "new")]),
        ("Run", [(["docker"], "Images", "one build", "new"), (["githubactions"], "CI", "checks every change", "new"),
                 (["box"], "Hall kit", "works offline", "new")]),
    ]
    y = 8
    for name, cards in rows:
        c.shapes.append(f'<text class="row" x="18" y="{y + 66}">{esc(name.upper())}</text>')
        for k, line in enumerate(ANALOGUE.get(name, "").split("\n")):
            c.shapes.append(f'<text class="s" x="18" y="{y + 84 + 14 * k}" style="font-size:11px">{esc(line)}</text>')
        for i, (icons, title, caption, cls) in enumerate(cards):
            c.card(150 + i * 218, y, icons, title, caption, cls, 206)
        y += Card.H + 16
    return c.svg()


def planner() -> str:
    c = Canvas(1240, "The planner: an incident is assembled from the graph and knowledge, then the allocator and the agent team work in parallel, the better plan wins, a person approves high-impact actions, and the gate sends the call.")
    top, mid, low = 110, 260, 410
    c.frame(212, 48, 818, 512)
    c.shapes.append(f'<image href="{logo_uri("langgraph")[0]}" x="228" y="56" width="22" height="22"/>')
    c.label(258, 72, "LANGGRAPH · PER INCIDENT", "start")
    incident = c.card(20, mid, ["alert"], "Incident", "needs attention")
    assemble = c.card(225, mid, ["neo4j", "qdrant"], "Assemble", "graph and knowledge")
    solve = c.card(430, top, ["ortools"], "Solve", "milliseconds, offline", "new")
    team = c.card(430, low, ["langchain", "groq"], "Deliberate", "LangChain agent team")
    rec = c.card(635, mid, ["scale"], "Reconcile", "better plan wins", "new")
    person = c.card(840, top, ["person"], "A person", "approves valve and grid", "new")
    app = c.card(840, mid, ["lock"], "Approve", "pause until signed", "new")
    gate = c.card(1045, mid, ["lock"], "Gate", "checks and signs", "gate")
    store = c.card(635, low, ["sqlite"], "Checkpoints", "resume and replay", "new")
    twin = c.card(1045, low, ["city"], "Twin", "carries it out", "partner")
    c.arrow(f"M{incident.right} {incident.cy} H{assemble.x}")
    c.arrow(f"M{assemble.right} {assemble.cy - 14} H{solve.x - 18} V{solve.cy} H{solve.x}")
    c.arrow(f"M{assemble.right} {assemble.cy + 14} H{team.x - 18} V{team.cy} H{team.x}")
    c.arrow(f"M{solve.right} {solve.cy} H{rec.x - 18} V{rec.cy - 14} H{rec.x}")
    c.arrow(f"M{team.right} {team.cy} H{rec.x - 18} V{rec.cy + 14} H{rec.x}")
    c.arrow(f"M{rec.right} {rec.cy} H{app.x}")
    c.arrow(f"M{app.right} {app.cy} H{gate.x}")
    c.arrow(f"M{person.cx} {person.bottom} V{app.y}")
    c.arrow(f"M{gate.cx} {gate.bottom} V{twin.y}", "ember")
    c.arrow(f"M{rec.cx} {rec.bottom} V{store.y}")
    c.arrow(f"M{solve.cx} {solve.y} V28 H{gate.cx} V{gate.y}", "ember")
    c.label(solve.cx + 14, 22, "fast path: first proposals go straight to the gate", "start")
    return c.svg()


def memory() -> str:
    c = Canvas(1240, "One brain and five stores, each answering a different question: what connects, why, what we know, what happened, and what state we are in.")
    brain = c.card(532, 8, ["brain"], "City Brain", "decisions read memory only", "", 176)
    stores = [
        (["networkx"], "City graph", "what connects", ""),
        (["neo4j"], "Graph database", "why and what fails", ""),
        (["qdrant"], "Vector store", "what we know", "new"),
        (["file"], "Event log", "every step, chained", ""),
        (["sqlite"], "State", "approvals and checkpoints", "new"),
    ]
    for i, (icons, title, caption, cls) in enumerate(stores):
        card = c.card(30 + i * 238, 230, icons, title, caption, cls, 214)
        c.arrow(f"M{brain.cx} {brain.bottom} V190 H{card.cx} V{card.y}")
    c.label(1210, 392, "Every store has a fallback: the decision path never waits on a database.", "end", "s")
    return c.svg()


def run_anywhere() -> str:
    c = Canvas(1240, "Deployment: Compose on one laptop is the default on stage; the full profile adds Qdrant and Neo4j, and an observability row is optional.")
    c.frame(300, 8, 920, 336, "ONE LAPTOP, DOCKER COMPOSE")
    app = [
        (["python"], "Brain", "screen, API, tools", "new"), (["city", "shield"], "Mock Twin and Guardian", "swap for the real ones", "partner"),
        (["qdrant"], "Qdrant", "vector store", "new"), (["neo4j"], "Neo4j", "graph database", ""),
    ]
    obs = [
        (["opentelemetry"], "OpenTelemetry", "spans", "new"), (["jaeger"], "Jaeger", "traces", "new"),
        (["prometheus"], "Prometheus", "metrics", "new"), (["grafana"], "Grafana", "dashboards", "new"),
    ]
    cards = []
    for i, (icons, title, caption, cls) in enumerate(app):
        cards.append(c.card(320 + i * 225, 44, icons, title, caption, cls, 205))
    c.label(320, 196, "OPTIONAL ON STAGE", "start")
    for i, (icons, title, caption, cls) in enumerate(obs):
        cards.append(c.card(320 + i * 225, 206, icons, title, caption, cls, 205))
    docker = c.card(30, 156, ["docker"], "Docker Compose", "default on stage", "new", 230)
    kit = c.card(300, 380, ["box"], "Hall kit", "images and models, no network", "new", 250)
    ci = c.card(580, 380, ["githubactions"], "CI", "tests, images", "new", 230)
    c.arrow(f"M{docker.right} {docker.cy} H{kit.x - 20} V{kit.cy} H{kit.x}")
    return c.svg()


def protocols() -> str:
    c = Canvas(1240, "Protocols, link by link: the one we chose on the left and the options we looked at on the right, each with a short reason.")
    rows = [
        ("READINGS AND ACTIONS", ["modelcontextprotocol"], "MCP", "tools with schemas, cursor", "",
         [("mqtt", "MQTT", "needs a broker\nadapter built", True), ("ws", "WebSocket", "no schema,\nno replay", False), ("grpc", "gRPC", "heavy\ntoolchain", False), ("apachekafka", "Kafka", "needs\ninfrastructure", False)]),
        ("TRUST VERDICTS", ["openapiinitiative"], "REST", "one question, one answer", "",
         [("modelcontextprotocol", "MCP", "not an agent\ntool", False), ("grpc", "gRPC", "heavy\ntoolchain", False)]),
        ("LIVE FEED", ["sse", "cloudevents"], "SSE + CloudEvents", "one way, replays, reconnects", "",
         [("ws", "WebSocket", "two-way not\nneeded", False), ("poll", "Polling", "wasteful,\nno order", False)]),
        ("OTHER AGENTS", ["modelcontextprotocol"], "MCP", "read-only tools, agent card", "new",
         [("openapiinitiative", "REST only", "no tool\ndiscovery", False)]),
        ("TELEMETRY", ["opentelemetry", "prometheus"], "OTLP and Prometheus", "vendor neutral", "new", []),
        ("SIGNING AND ACCESS", ["jsonwebtokens", "shield"], "HMAC, Ed25519, JWT", "keys, scopes, expiry", "new",
         [("openssl", "TLS", "on every link,\noptional mutual", True)]),
    ]
    y = 10
    for label, icons, title, caption, cls, alts in rows:
        c.shapes.append(f'<text class="row" x="18" y="{y + 70}">{esc(label)}</text>')
        card = c.card(250, y, icons, title, caption, cls, 230)
        if alts:
            c.shapes.append(f'<text class="k" x="520" y="{y + 18}">LOOKED AT, NOT THE DEFAULT</text>')
            c.arrow(f"M{card.right} {card.cy} H505")
        for i, (icon, name, why, built) in enumerate(alts):
            c.mini(520 + i * 134, y + 28, icon, name, why, built)
        y += Card.H + 14
    return c.svg()


def defence() -> str:
    c = Canvas(1240, "Security in six layers a request must pass, from the network to the audit trail, and the three things that enforce them.")
    layers = [
        (["openssl"], "Network", "TLS, loopback ports", "new"),
        (["jsonwebtokens", "fastapi"], "Edge", "tokens, size, rate limits", "new"),
        (["pydantic", "shield"], "Message", "signed, replay-proof", ""),
        (["agents"], "Decision", "code checks the agents", ""),
        (["lock"], "Action", "the gate, a person for risk", "gate"),
        (["file", "sqlite"], "Audit", "chained, signed, replayable", ""),
    ]
    cards = [c.card(14 + i * 204, 14, icons, title, caption, cls, 186) for i, (icons, title, caption, cls) in enumerate(layers)]
    for a, b in zip(cards, cards[1:]):
        c.arrow(f"M{a.right} {a.cy} H{b.x}")
    c.shapes.append('<text class="row" x="14" y="196">ENFORCED BY</text>')
    c.card(14, 210, ["pytest"], "Invariant tests", "the gate is the only way out", "new", 240)
    c.card(272, 210, ["githubactions"], "CI", "every change, every image", "new", 240)
    c.card(530, 210, ["file"], "Security report", "each threat, its test, its result", "new", 240)
    c.label(800, 270, "A control with no passing test is listed as open.", "start", "s")
    return c.svg()


def whose() -> str:
    c = Canvas(1240, "Who decides what: the Brain team alone, the whole triplet, or the shared contract.")
    groups = [
        ("OURS ALONE", 14, [
            (["python"], "Language", "Python and JavaScript", ""), (["neo4j", "qdrant"], "Databases", "five stores", ""),
            (["langgraph", "ortools"], "AI methods", "each for its job", ""), (["threedotjs"], "Our screen", "Strip Board, canopy", "")]),
        ("THE TRIPLET DECIDES", 404, [
            (["modelcontextprotocol", "mqtt"], "Protocols", "per link, with adapters", "new"), (["docker"], "Hosting", "one compose, one router", "new"),
            (["file"], "Test Book", "scenarios and triggers", "new"), (["sse", "cloudevents"], "Shared screen", "whose events appear", "new")]),
        ("THE CONTRACT", 794, [
            (["pydantic"], "Message formats", "Data Dictionary", ""), (["shield"], "Signing", "keys and rotation", "new"),
            (["openapiinitiative"], "Interface Card", "one page each", ""), (["loop"], "Versions", "four edits", "")]),
    ]
    for label, x, cards in groups:
        c.frame(x, 10, 376, 340, label)
        for i, (icons, title, caption, cls) in enumerate(cards):
            c.card(x + 12 + (i % 2) * 182, 34 + (i // 2) * 150, icons, title, caption, cls, 170)
    c.label(620, 380, "Anything in the middle column is proposed to the Twin and Guardian teams first, with the alternative we can connect to.", "middle", "s")
    return c.svg()

def tech_map() -> str:
    """Every technology in one picture: six groups, what each holds, and what flows between the groups."""
    c = Canvas(1240, "All the technologies together in six groups: the world, the edge, the core, memory, observability and the platform, with the protocol that carries what flows between them.")
    groups = [
        ("THE WORLD · THE BODY AND THE WORLD, OUTSIDE THE BRAIN", [
            (["city"], "Twin", "MCP server", "partner"), (["shield"], "Guardian", "REST service", "partner"),
            (["modelcontextprotocol"], "Other teams", "agents over MCP", "new"), (["person"], "People", "screen, approver", "new"),
            (["threedotjs"], "Screen", "Strip Board, canopy", "")]),
        ("THE EDGE · SENSORY INPUT AND MOTOR OUTPUT", [
            (["modelcontextprotocol"], "MCP", "Twin link, our server", ""), (["openapiinitiative"], "REST", "Guardian link", ""),
            (["fastapi"], "FastAPI", "API, approvals", ""), (["sse", "cloudevents"], "SSE", "CloudEvents feed", ""),
            (["pydantic"], "Contracts", "checked on entry", ""), (["jsonwebtokens", "openssl"], "Auth, TLS", "tokens, certificates", "new"),
            (["agents"], "Agent card", "discovery", "new")]),
        ("THE CORE · THALAMUS, CEREBELLUM, AMYGDALA, WORKSPACE, PREFRONTAL, BASAL GANGLIA", [
            (["python"], "Python", "perception, triage, rules", ""), (["numpy"], "NumPy", "forward models, Kalman", ""),
            (["langgraph"], "LangGraph", "reflex graph, planner", ""), (["langchain", "groq"], "LangChain", "agent team", ""),
            (["ortools"], "OR-Tools", "allocator", "new"), (["lock"], "Gate", "the only way out", "gate")]),
        ("MEMORY · HIPPOCAMPUS", [
            (["networkx"], "NetworkX", "city graph in memory", ""), (["neo4j"], "Neo4j", "provenance, analytics", ""),
            (["qdrant", "huggingface"], "Qdrant", "knowledge, stories", "new"), (["sqlite"], "SQLite", "state, checkpoints", ""),
            (["file"], "Event log", "hash-chained", "")]),
        ("OBSERVE · NOT BIOLOGICAL", [
            (["opentelemetry"], "OpenTelemetry", "spans", "new"), (["jaeger"], "Jaeger", "trace view", "new"),
            (["prometheus"], "Prometheus", "metrics", "new"), (["grafana"], "Grafana", "dashboards", "new"),
            (["file"], "PROV", "provenance export", "new")]),
        ("RUN · NOT BIOLOGICAL · HOSTS ALL OF THE ABOVE", [
            (["docker"], "Docker", "images, Compose", "new"), (["githubactions"], "CI", "checks", "new"),
            (["uv", "pytest"], "uv, pytest", "locked, tested", ""), (["box"], "Hall kit", "offline", "new")]),
    ]
    y, tops = 8, []
    for label, cards in groups:
        c.frame(14, y, 1212, 188, label)
        for i, (icons, title, caption, cls) in enumerate(cards):
            c.card(28 + i * 172, y + 36, icons, title, caption, cls, 160)
        tops.append(y)
        y += 188 + 46
    links = [
        (0, [(110, "readings and actions · MCP"), (300, "verdicts · REST"), (500, "tools · MCP"), (720, "approvals · REST"), (930, "live feed · SSE")]),
        (1, [(200, "validated, signed, typed messages")]),
        (2, [(200, "reads memory only"), (620, "writes behind: Bolt, REST, SQL")]),
        (3, [(300, "every event: spans and metrics")]),
    ]
    for gap, items in links:
        top, bottom = tops[gap] + 188, tops[gap + 1]
        for x, text in items:
            c.arrow(f"M{x} {top} V{bottom}", both=True)
            c.label(x + 10, top + 28, text, "start", "s")
    return c.svg()


def incident_flow() -> str:
    """From a sensor reading to an action on the city, one card per step, each tagged with the part of a brain it models."""
    c = Canvas(1240, "The flow from a reading to a decision in eighteen steps: the Twin's reading, perception, the Guardian, forward models, triage, the workspace, then packs, the reflex tier, the solver, the agent team, reconcile and the verifiers, then the gate, approval, the Twin's action, the log and screen, memory with sleep, and the explanation. Each step carries the brain region it models.")
    W, GAP = 184, 22
    xs = [14 + i * (W + GAP) for i in range(6)]
    H = 150
    r1, r2, r3 = 8, 8 + H + 56, 8 + 2 * (H + 56)
    top = [
        (["city"], "1 Reading", "a signed sensor reading", "partner", "the world"),
        (["eye", "pydantic"], "2 Perception", "signature, replay, ranges", "", "thalamic gating"),
        (["shield"], "3 Verdict", "the Guardian judges it", "partner", "another team's judgement"),
        (["numpy"], "4 Forward models", "does it fit its history", "", "cerebellum: surprise"),
        (["alert"], "5 Triage", "an incident opens", "", "amygdala: the fast route"),
        (["brain"], "6 Workspace", "two slots of attention", "", "global workspace"),
    ]
    mid = [  # drawn right to left
        (["agents"], "7 Departments bid", "who can answer", "", "specialised modules"),
        (["python", "langgraph"], "8 Reflex", "rules act at once", "", "reflexes and habits"),
        (["ortools"], "9 Solve", "allocator, milliseconds", "new", "a solver, no analogue"),
        (["langchain", "groq"], "10 Deliberate", "agent team, seconds", "", "prefrontal"),
        (["scale"], "11 Reconcile", "the better plan wins", "new", "habit vs deliberation"),
        (["shield"], "12 Verify", "code checks the agents", "", "conflict monitor (code)"),
    ]
    low = [
        (["lock"], "13 Gate", "eleven checks, then sign", "gate", "basal ganglia"),
        (["person", "jsonwebtokens"], "14 Approval", "a person, for risk", "new", "outside the brain"),
        (["city"], "15 Action", "the Twin carries it out", "partner", "the body"),
        (["file", "threedotjs"], "16 Log and screen", "chained, live", "", "the record"),
        (["neo4j", "moon"], "17 Memory, sleep", "episodes, then reflexes", "", "hippocampus, replay"),
        (["loop"], "18 Explain", "why, from the log", "", "reasons, rebuilt by code"),
    ]
    row1 = [c.card(xs[i], r1, *step[0:1], step[1], step[2], step[3], W, tag=step[4]) for i, step in enumerate(top)]
    row2 = [c.card(xs[5 - i], r2, *step[0:1], step[1], step[2], step[3], W, tag=step[4]) for i, step in enumerate(mid)]
    row3 = [c.card(xs[i], r3, *step[0:1], step[1], step[2], step[3], W, tag=step[4]) for i, step in enumerate(low)]
    for a, b in zip(row1, row1[1:]):
        c.arrow(f"M{a.right} {a.cy} H{b.x}")
    c.arrow(f"M{row1[5].cx} {row1[5].bottom} V{row2[0].y}")
    for a, b in zip(row2, row2[1:]):
        c.arrow(f"M{a.x} {a.cy} H{b.right}")
    c.arrow(f"M{row2[5].cx} {row2[5].bottom} V{row3[0].y}")
    for a, b in zip(row3, row3[1:3]):
        c.arrow(f"M{a.right} {a.cy} H{b.x}", "ember")
    c.arrow(f"M{row3[2].right} {row3[2].cy} H{row3[3].x}")
    c.arrow(f"M{row3[3].right} {row3[3].cy} H{row3[4].x}")
    # the reflex tier acts at once: its proposals go straight to the gate
    gap_y = row2[0].bottom + 28
    c.arrow(f"M{row2[1].cx - 30} {row2[1].bottom} V{gap_y} H{row3[0].cx + 40} V{row3[0].y}", "ember")
    c.label(row3[0].cx + 70, gap_y - 8, "reflex proposals reach the gate at once", "start", "s")
    # the timeline also feeds the explanation, along the foot of the row
    foot = row3[3].bottom + 18
    c.arrow(f"M{row3[3].cx} {row3[3].bottom} V{foot} H{row3[5].cx} V{row3[5].bottom}")
    # sleep compiles verified plans back into reflexes: a habit
    c.arrow(f"M{row3[4].cx + 30} {row3[4].y} V{row2[1].bottom}")
    c.label(row3[4].cx + 40, row3[4].y - 14, "habit: verified plans return as reflexes", "start", "s")
    c.low = max(c.low, row3[0].bottom + 40)
    return c.svg()


TOOLBOX = [
    ("python", "Python", "Brain core", True), ("fastapi", "FastAPI", "API and feed", True), ("modelcontextprotocol", "MCP", "tools for agents", True),
    ("langgraph", "LangGraph", "orchestration", True), ("langchain", "LangChain", "model clients", True), ("ortools", "OR-Tools", "optimisation", False), ("numpy", "NumPy", "maths", False),
    ("networkx", "NetworkX", "graph analytics", True), ("neo4j", "Neo4j", "graph database", True), ("qdrant", "Qdrant", "vector search", False),
    ("huggingface", "Hugging Face", "embedding models", True), ("groq", "Groq", "fast language model", True), ("anthropic", "Anthropic", "Claude models", True),
    ("pydantic", "Pydantic", "contracts", True), ("sqlite", "SQLite", "state", True), ("threedotjs", "three.js", "the screen", True),
    ("docker", "Docker", "images", False), ("opentelemetry", "OpenTelemetry", "traces", False), ("prometheus", "Prometheus", "metrics", False),
    ("grafana", "Grafana", "dashboards", False), ("jaeger", "Jaeger", "trace view", False), ("githubactions", "GitHub Actions", "CI", False),
    ("pytest", "pytest", "tests", True), ("uv", "uv", "locked builds", True),
    ("mqtt", "MQTT", "second transport", False), ("eclipsemosquitto", "Mosquitto", "MQTT broker", False), ("openapiinitiative", "OpenAPI", "REST contract", True),
    ("jsonwebtokens", "JWT", "short-lived tokens", False), ("openssl", "OpenSSL", "local certificates", False), ("cloudevents", "CloudEvents", "event envelope", True),
]


def wall() -> str:
    out = []
    for name, title, role, built in TOOLBOX:
        uri, aspect = logo_uri(name)
        w = min(96, max(40, round(40 * aspect)))
        out.append(f'<figure class="{"built" if built else "planned"}"><div class="chip"><img src="{uri}" alt="{esc(title)} logo" width="{w}" height="40"></div>'
                   f'<figcaption><b>{esc(title)}</b><span>{esc(role)}</span></figcaption></figure>')
    return "".join(out)


PAGE = """<title>Architecture in Logos</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Familjen+Grotesk:wght@500;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: a short reading column, then wide diagrams that scroll inside their own box. Logos sit on white tiles so brand colours read in both themes. Accent fill marks what is proposed; amber marks the gate. */
:root { --bg:#F2F4F5; --panel:#FFFFFF; --fg:#10161C; --muted:#51606D; --line:#C5CED5; --steel:#31597E; --ember:#A8590A; --good:#17724A; --wash:#E6EBEE; --new:#DCE8F3; --tile:#FFFFFF;
  --display:'Familjen Grotesk','Helvetica Neue',Arial,sans-serif; --body:'IBM Plex Sans','Helvetica Neue',Arial,sans-serif; --mono:'IBM Plex Mono',ui-monospace,Menlo,monospace; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0B1118; --panel:#121A23; --fg:#E8E5DA; --muted:#9AA8B5; --line:#2B3947; --steel:#7FA3C4; --ember:#F2B552; --good:#4CC38A; --wash:#18222D; --new:#1B2D41; color-scheme: dark; } }
:root[data-theme="dark"] { --bg:#0B1118; --panel:#121A23; --fg:#E8E5DA; --muted:#9AA8B5; --line:#2B3947; --steel:#7FA3C4; --ember:#F2B552; --good:#4CC38A; --wash:#18222D; --new:#1B2D41; color-scheme: dark; }
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--fg); font: 16px/1.5 var(--body); padding-block: 40px 96px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
main { max-width: 1240px; margin: 0 auto; display: flex; flex-direction: column; gap: 56px; }
header, section > :not(.wide):not(.wall) { max-width: 62ch; }
h1 { font: 700 clamp(2.4rem, 6vw, 3.8rem)/1.02 var(--display); letter-spacing: -.02em; margin: 0 0 14px; text-wrap: balance; }
h2 { font: 700 1.6rem/1.15 var(--display); letter-spacing: -.01em; margin: 0 0 8px; text-wrap: balance; }
p { margin: 0 0 10px; } .lead { font-size: 1.1rem; }
.date { font: 500 .85rem var(--mono); color: var(--muted); letter-spacing: .04em; margin-bottom: 12px; }
.wide { max-width: none; overflow-x: auto; border: 1px solid var(--line); background: var(--panel); border-radius: 8px; margin-top: 14px; }
.wide svg { display: block; min-width: 1000px; width: 100%; height: auto; }
.card { fill: var(--panel); stroke: var(--line); stroke-width: 1.4; } .card.new { fill: var(--new); stroke: var(--steel); } .card.partner { stroke-dasharray: 6 4; stroke: var(--muted); fill: var(--wash); } .card.gate { stroke: var(--ember); stroke-width: 2.4; fill: var(--wash); }
.tile { fill: #FFFFFF; stroke: #D5DCE1; stroke-width: 1; } .glyph { fill: none; stroke: #31597E; stroke-width: 2.6; stroke-linecap: round; stroke-linejoin: round; }
.frame { fill: none; stroke: var(--line); stroke-width: 1.2; stroke-dasharray: 2 5; }
.cortex, .cbl, .stem { fill: var(--wash); stroke: var(--steel); stroke-width: 1.3; } .cbl { stroke-dasharray: 3 4; } .wire { fill: none; stroke: var(--steel); stroke-width: 1.5; opacity: .7; } .wire.out { stroke: var(--ember); opacity: 1; stroke-width: 2; } .tipfill { fill: var(--steel); } .dot { fill: var(--steel); } .dot.gate { fill: var(--ember); } .dot.agent { fill: #6B4FA0; } .dot.twin { fill: var(--muted); } .arrow { fill: none; stroke: var(--steel); stroke-width: 1.8; } .arrow.ember { stroke: var(--ember); } .headfill { fill: var(--steel); } .headember { fill: var(--ember); }
svg .an { font: 500 10.5px var(--mono); fill: var(--steel); letter-spacing: .03em; } svg .t { font: 600 16px var(--body); fill: var(--fg); } svg .s { font: 400 12.5px var(--body); fill: var(--muted); } svg .k { font: 500 11px var(--mono); fill: var(--muted); letter-spacing: .06em; } svg .row { font: 700 13px var(--mono); fill: var(--muted); letter-spacing: .12em; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 20px; font-size: .9rem; color: var(--muted); margin: 8px 0 0; max-width: none; }
.legend span::before { content: ""; display: inline-block; width: 18px; height: 12px; margin-right: 7px; vertical-align: -1px; border: 1.4px solid var(--line); border-radius: 3px; background: var(--panel); }
.legend .n::before { background: var(--new); border-color: var(--steel); } .legend .p::before { border-style: dashed; border-color: var(--muted); background: var(--wash); } .legend .g::before { border-color: var(--ember); border-width: 2px; background: var(--wash); }
.wall { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; margin-top: 14px; }
.wall figure { margin: 0; background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.wall .planned { background: var(--new); border-color: var(--steel); }
.chip { background: #FFFFFF; border: 1px solid #D5DCE1; border-radius: 8px; height: 62px; display: grid; place-items: center; } .chip img { max-width: calc(100% - 16px); object-fit: contain; }
.wall figcaption { display: flex; flex-direction: column; font-size: .8rem; color: var(--muted); } .wall figcaption b { font: 600 .95rem var(--body); color: var(--fg); }
.tag { display: inline-block; font: 500 .72rem var(--mono); letter-spacing: .04em; padding: 1px 7px; border: 1.5px solid currentColor; border-radius: 3px; white-space: nowrap; color: var(--ember); }
footer { color: var(--muted); font-size: .85rem; border-top: 1px solid var(--line); padding-top: 18px; max-width: 72ch; }
</style>
<main>
<header>
<p class="date">4 NOVEMBER 2026 · <span class="tag">PROPOSED, PART BUILT</span></p>
<h1>Architecture in Logos</h1>
<p class="lead">The same design as the full diagrams, drawn so each part is one logo and a few words.</p>
<p class="legend"><span>built today</span><span class="n">proposed</span><span class="p">another team's layer</span><span class="g">the gate</span></p>
</header>

<section id="tech">
<h2>All the technologies together</h2>
<p>Six groups. The arrows say what flows between them and over which protocol.</p>
<div class="wide" tabindex="0" role="region" aria-label="Technology map, scrolls sideways on a narrow screen">__TECH__</div>
</section>

<section id="flow">
<h2>From incident to decision</h2>
<p>Eighteen steps. Each card names the part of a brain it models, in blue. Amber arrows are the way out.</p>
<div class="wide" tabindex="0" role="region" aria-label="Incident to decision flow, scrolls sideways on a narrow screen">__FLOW__</div>
</section>

<section id="big">
<h2>The big picture</h2>
<p>Readings in, verdicts back, actions out through one gate.</p>
<div class="wide" tabindex="0" role="region" aria-label="Big picture diagram, scrolls sideways on a narrow screen">__BIG__</div>
</section>

<section id="brain">
<h2>The brain behind it</h2>
<p>Every row of the stack is a region of the glass brain. The violet one is where the agents live.</p>
<div class="wide" tabindex="0" role="region" aria-label="Side view of the glass brain, scrolls sideways on a narrow screen">__BRAINVIEW__</div>
</section>

<section id="stack">
<h2>The stack</h2>
<p>Nine rows, one job each.</p>
<div class="wide" tabindex="0" role="region" aria-label="Stack diagram, scrolls sideways on a narrow screen">__STACK__</div>
</section>

<section id="deciding">
<h2>Deciding</h2>
<p>The solver is fast and always there. The agent team is slower and can improve on it. A person approves what is risky.</p>
<div class="wide" tabindex="0" role="region" aria-label="Planner diagram, scrolls sideways on a narrow screen">__PLANNER__</div>
</section>

<section id="whose">
<h2>Whose choice is it?</h2>
<p>"Choose what your triplet can build and defend." Some choices are ours, some need the partners.</p>
<div class="wide" tabindex="0" role="region" aria-label="Who decides what, scrolls sideways on a narrow screen">__WHOSE__</div>
</section>

<section id="protocols">
<h2>Protocols</h2>
<p>One protocol per link, and the options we looked at.</p>
<div class="wide" tabindex="0" role="region" aria-label="Protocols diagram, scrolls sideways on a narrow screen">__PROTOCOLS__</div>
</section>

<section id="security">
<h2>Security</h2>
<p>Six layers, each assuming the one outside it can fail.</p>
<div class="wide" tabindex="0" role="region" aria-label="Security layers diagram, scrolls sideways on a narrow screen">__DEFENCE__</div>
</section>

<section id="memory">
<h2>Remembering</h2>
<p>Five stores. Each answers a question the others answer badly.</p>
<div class="wide" tabindex="0" role="region" aria-label="Memory diagram, scrolls sideways on a narrow screen">__MEMORY__</div>
</section>

<section id="run">
<h2>Running it anywhere</h2>
<p>One laptop with no network on stage. A cluster when there is one.</p>
<div class="wide" tabindex="0" role="region" aria-label="Deployment diagram, scrolls sideways on a narrow screen">__RUN__</div>
</section>

<section id="toolbox">
<h2>The toolbox</h2>
<p>Every technology and its one job. Tinted tiles are proposed; plain tiles are in the Brain today.</p>
<div class="wall">__WALL__</div>
</section>

<footer>Logos identify the tools the Brain uses or plans to use. They belong to their owners: most come from Simple Icons (CC0 files), the rest from each project's own site or repository. Sources are in <code>docs/diagrams/logos/README.md</code>. The Brain is brain-inspired: it models functions such as attention and sleep.</footer>
</main>
"""


def main() -> None:
    page = (PAGE.replace("__TECH__", tech_map()).replace("__FLOW__", incident_flow()).replace("__BRAINVIEW__", side_view()).replace("__BIG__", big_picture()).replace("__STACK__", stack()).replace("__PLANNER__", planner())
            .replace("__WHOSE__", whose()).replace("__PROTOCOLS__", protocols()).replace("__DEFENCE__", defence()).replace("__MEMORY__", memory()).replace("__RUN__", run_anywhere()).replace("__WALL__", wall()))
    OUT.write_text(page)
    print(f"wrote {OUT} ({len(page) // 1024} KB)")


if __name__ == "__main__":
    main()
