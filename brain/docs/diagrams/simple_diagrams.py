"""Writes docs/simple-diagrams.html and docs/diagrams/simple/*.svg: how the City Brain works, for someone who has never seen it.

    uv run python docs/diagrams/simple_diagrams.py

One small vocabulary throughout: a card with an icon, a labelled arrow, and a swimlane for an execution flow. The parts carry the same
plain names as the screen. The flows are the Test Book's real scenarios (d2 to d4) (`uv run brain scenario d3 --inproc --speed 0` shows the same
order); numbers in them come from those runs. The SVG files stand alone for the report and the deck; the page themes the same drawings.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from logo_architecture import GLYPHS, esc, logo_uri  # noqa: E402

HERE = Path(__file__).resolve().parent
PAGE = HERE.parent / "simple-diagrams.html"
FILES = HERE / "simple"

GLYPHS.update({
    "camera": '<rect x="5" y="14" width="30" height="20" rx="3"/><path d="M35 21l9-5v16l-9-5"/><circle cx="17" cy="24" r="4"/>',
    "flame": '<path d="M24 5c2 9 12 13 12 25a12 12 0 0 1-24 0c0-6 4-9 5-14 3 2 4 5 4 7 3-4 4-11 3-18z"/>',
    "unit": '<path d="M6 32v-8l5-11h26l5 11v8z"/><path d="M6 24h36"/><circle cx="15" cy="34" r="4"/><circle cx="33" cy="34" r="4"/>',
    "alert2": '<path d="M7 20v9l6 1 22 9V10L13 19z"/><path d="M13 30l3 10h5l-3-8"/><path d="M41 19v11"/>',
    "drop": '<path d="M24 5c7 10 14 17 14 25a14 14 0 0 1-28 0c0-8 7-15 14-25z"/>',
    "phone": '<path d="M12 6l7 3 2 10-5 3c2 5 5 8 10 10l3-5 10 2 3 7c-2 5-6 6-9 6C20 41 7 28 6 15c0-4 2-8 6-9z"/>',
    "signal": '<rect x="16" y="4" width="16" height="32" rx="4"/><circle cx="24" cy="12" r="3"/><circle cx="24" cy="20" r="3"/><circle cx="24" cy="28" r="3"/><path d="M24 36v8"/>',
    "key": '<circle cx="15" cy="24" r="9"/><path d="M24 24h19M36 24v8M43 24v6"/>',
    "db": '<ellipse cx="24" cy="10" rx="16" ry="6"/><path d="M8 10v28c0 3 7 6 16 6s16-3 16-6V10M8 24c0 3 7 6 16 6s16-3 16-6"/>',
    "clock": '<circle cx="24" cy="24" r="18"/><path d="M24 12v12l8 6"/>',
    "search": '<circle cx="21" cy="21" r="14"/><path d="M31 31l12 12"/>',
    "stop": '<path d="M16 5h16l11 11v16L32 43H16L5 32V16z"/><path d="M16 24h16"/>',
    "check": '<circle cx="24" cy="24" r="18"/><path d="M15 25l6 6 12-14"/>',
    "chain": '<rect x="4" y="17" width="20" height="14" rx="7"/><rect x="24" y="17" width="20" height="14" rx="7"/><path d="M17 24h14"/>',
    "bolt": '<path d="M28 4L9 28h13l-3 16 20-25H25z"/>',
    "book": '<path d="M24 12C19 7 11 7 5 9v29c6-2 14-2 19 3 5-5 13-5 19-3V9c-6-2-14-2-19 3z"/><path d="M24 12v29"/>',
    "route": '<circle cx="10" cy="38" r="5"/><circle cx="38" cy="10" r="5"/><path d="M15 38h15a7 7 0 0 0 0-14H18a7 7 0 0 1 0-14h15"/>',
    "plug": '<path d="M17 5v11M31 5v11M11 16h26v8a13 13 0 0 1-26 0z"/><path d="M24 37v7"/>',
    "stamp": '<path d="M18 26c0-5-4-7-4-13a10 10 0 0 1 20 0c0 6-4 8-4 13z"/><path d="M8 34c0-4 3-8 8-8h16c5 0 8 4 8 8v3H8zM8 43h32"/>',
    "chart": '<path d="M6 6v36h36"/><path d="M13 32l9-11 7 6 11-15"/>',
    "code": '<path d="M16 13L5 24l11 11M32 13l11 11-11 11M28 8l-8 32"/>',
    "tag": '<path d="M6 6h18l18 18-18 18L6 24z"/><circle cx="15" cy="15" r="3"/>',
    "waves": '<path d="M4 16c7-6 13 6 20 0s13 6 20 0M4 26c7-6 13 6 20 0s13 6 20 0M4 36c7-6 13 6 20 0s13 6 20 0"/>',
    "cross": '<circle cx="24" cy="24" r="18"/><path d="M16 16l16 16M32 16L16 32"/>',
})

KINDS = ("twin", "guardian", "brain", "gate", "person", "store", "bad", "good")
CSS_LIGHT = {"paper": "#F7F9FB", "card": "#FFFFFF", "ink": "#16202B", "ink2": "#4C5968", "line": "#C5CFD9", "lane": "#EEF2F6",
             "twin": "#0B7A75", "guardian": "#6D3FC4", "brain": "#1B5FD0", "gate": "#B86E00", "person": "#A62C7F", "store": "#4A6275", "bad": "#C7301E", "good": "#167A49"}
CSS_DARK = {"paper": "#0E141B", "card": "#17212C", "ink": "#EEF3F8", "ink2": "#AAB8C6", "line": "#3A4A5A", "lane": "#141D27",
            "twin": "#3CC8BE", "guardian": "#B597F5", "brain": "#7DAEFF", "gate": "#F2B552", "person": "#F08BCB", "store": "#92AEC4", "bad": "#FF8672", "good": "#5AD198"}
RULES = """.dcard{fill:var(--card);stroke:var(--line);stroke-width:1.5}.dt{font:700 14.5px var(--dfont);fill:var(--ink)}.ds{font:400 12.5px var(--dfont);fill:var(--ink2)}
.dl{font:700 12px var(--dfont);fill:var(--ink2);paint-order:stroke;stroke:var(--paper);stroke-width:5px;stroke-linejoin:round}
.dw{fill:none;stroke:var(--ink2);stroke-width:2}.dw.good{stroke:var(--good)}.dw.bad{stroke:var(--bad)}.dw.gate{stroke:var(--gate)}.dw.dash{stroke-dasharray:6 5}
.dh{fill:var(--ink2)}.dh.good{fill:var(--good)}.dh.bad{fill:var(--bad)}.dh.gate{fill:var(--gate)}
.dg{fill:none;stroke-width:3;stroke-linecap:round;stroke-linejoin:round}.dlogo{fill:#fff;stroke:var(--line)}
.dband{fill:var(--lane);stroke:none}.dframe{fill:none;stroke:var(--line);stroke-width:1.5;stroke-dasharray:5 5}.dn{font:700 12px var(--dfont);fill:var(--card);text-anchor:middle}
""" + "".join(f".k-{k} .dg{{stroke:var(--{k})}}.k-{k} .dtint{{fill:var(--{k});fill-opacity:.14}}.k-{k} .dedge{{stroke:var(--{k});stroke-width:2.5}}.k-{k} .dnum{{fill:var(--{k})}}" for k in KINDS)
ALL = "".join(f"--{k}:{v};" for k, v in CSS_LIGHT.items())


def wrap(text: str, chars: int) -> list[str]:
    lines, now = [], ""
    for word in text.split():
        if now and len(now) + 1 + len(word) > chars:
            lines.append(now)
            now = word
        else:
            now = f"{now} {word}".strip()
    return lines + ([now] if now else [])


class Box:
    def __init__(self, x: float, y: float, w: float, h: float) -> None:
        self.x, self.y, self.w, self.h = x, y, w, h

    l = property(lambda s: (s.x, s.y + s.h / 2))
    r = property(lambda s: (s.x + s.w, s.y + s.h / 2))
    t = property(lambda s: (s.x + s.w / 2, s.y))
    b = property(lambda s: (s.x + s.w / 2, s.y + s.h))


class D:
    def __init__(self, slug: str, title: str, caption: str, width: int = 1240) -> None:
        self.slug, self.title, self.caption, self.width, self.out, self.low = slug, title, caption, width, [], 0

    def icon(self, names: str | list[str], cx: float, cy: float, r: float = 23) -> str:
        names = [names] if isinstance(names, str) else names
        parts, step = [], r * 2 + 6
        x0 = cx - step * (len(names) - 1) / 2
        for i, name in enumerate(names):
            x = x0 + i * step
            if name in GLYPHS:
                k = r * 1.2 / 48
                parts.append(f'<circle class="dtint" cx="{x:.1f}" cy="{cy}" r="{r}"/><g class="dg" transform="translate({x - 24 * k:.1f} {cy - 24 * k:.1f}) scale({k:.3f})">{GLYPHS[name]}</g>')
            else:
                uri, aspect = logo_uri(name)
                side = r * 1.25
                parts.append(f'<circle class="dlogo" cx="{x:.1f}" cy="{cy}" r="{r}"/><image href="{uri}" x="{x - side * min(aspect, 1.45) / 2:.1f}" y="{cy - side / 2:.1f}" width="{side * min(aspect, 1.45):.1f}" height="{side:.1f}" preserveAspectRatio="xMidYMid meet"/>')
        return "".join(parts)

    def card(self, x: float, y: float, icon: str | list[str], title: str, note: str = "", kind: str = "brain", w: float = 176, h: float = 0, num: int | None = None) -> Box:
        chars = int((w - 14) / 7.1)
        heads, notes = wrap(title, int((w - 14) / 8.4)), wrap(note, chars)
        h = h or 62 + 18 * len(heads) + 16 * len(notes) + 8
        out = [f'<g class="k-{kind}"><rect class="dcard" x="{x}" y="{y}" width="{w}" height="{h}" rx="12"/><rect class="dedge" x="{x + 14}" y="{y}" width="{w - 28}" height="0.1"/>', self.icon(icon, x + w / 2, y + 33)]
        ty = y + 76
        for row in heads:
            out.append(f'<text class="dt" x="{x + w / 2}" y="{ty}" text-anchor="middle">{esc(row)}</text>')
            ty += 18
        for row in notes:
            out.append(f'<text class="ds" x="{x + w / 2}" y="{ty}" text-anchor="middle">{esc(row)}</text>')
            ty += 16
        if num is not None:
            out.append(f'<circle class="dnum" cx="{x + 14}" cy="{y + 14}" r="11"/><text class="dn" x="{x + 14}" y="{y + 18.5}">{num}</text>')
        self.out.append("".join(out) + "</g>")
        self.low = max(self.low, y + h)
        return Box(x, y, w, h)

    def line(self, points: list[tuple[float, float]], label: str = "", kind: str = "", dash: bool = False, at: tuple[float, float] | None = None, anchor: str = "middle") -> None:
        """A path through the points, with an arrowhead drawn at the end. The head is a polygon so each file stands alone."""
        d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in points)
        (ax, ay), (bx, by) = points[-2], points[-1]
        length = max(((bx - ax) ** 2 + (by - ay) ** 2) ** .5, 1)
        ux, uy = (bx - ax) / length, (by - ay) / length
        head = f"{bx:.1f},{by:.1f} {bx - 11 * ux - 5.5 * uy:.1f},{by - 11 * uy + 5.5 * ux:.1f} {bx - 11 * ux + 5.5 * uy:.1f},{by - 11 * uy - 5.5 * ux:.1f}"
        self.out.append(f'<path class="dw {kind} {"dash" if dash else ""}" d="{d}"/><polygon class="dh {kind}" points="{head}"/>')
        if label:
            mid = at or ((points[0][0] + points[-1][0]) / 2, (points[0][1] + points[-1][1]) / 2 - 8)
            self.text(mid[0], mid[1], label, anchor)

    def go(self, a: Box, b: Box, label: str = "", kind: str = "", dash: bool = False, at: tuple[float, float] | None = None, anchor: str = "middle") -> None:
        """An arrow from one card to the next, straight when they line up and with one bend otherwise."""
        if a.y == b.y and (a.x + a.w <= b.x or b.x + b.w <= a.x):
            y = a.y + min(a.h, b.h) / 2
            pts = [(a.x + a.w, y), (b.x, y)] if a.x < b.x else [(a.x, y), (b.x + b.w, y)]
        elif abs(a.y + a.h / 2 - (b.y + b.h / 2)) < 2 and (a.x + a.w <= b.x or b.x + b.w <= a.x):
            p, q = (a.r, b.l) if a.x < b.x else (a.l, b.r)
            pts = [p, q]
        elif a.x + a.w <= b.x + 1:
            mid = (a.x + a.w + b.x) / 2
            pts = [a.r, (mid, a.r[1]), (mid, b.l[1]), b.l]
        elif b.x + b.w <= a.x + 1:
            mid = (b.x + b.w + a.x) / 2
            pts = [a.l, (mid, a.l[1]), (mid, b.r[1]), b.r]
        elif a.y + a.h <= b.y:
            pts = [(b.t[0], a.b[1]), b.t] if a.x <= b.t[0] <= a.x + a.w else [a.b, (a.b[0], (a.b[1] + b.y) / 2), (b.t[0], (a.b[1] + b.y) / 2), b.t]
        else:
            pts = [(b.b[0], a.t[1]), b.b] if a.x <= b.b[0] <= a.x + a.w else [a.t, (a.t[0], (a.y + b.b[1]) / 2), (b.b[0], (a.y + b.b[1]) / 2), b.b]
        self.line(pts, label, kind, dash, at, anchor)

    def text(self, x: float, y: float, label: str, anchor: str = "middle") -> None:
        for i, row in enumerate(label.split("\n")):
            self.out.append(f'<text class="dl" x="{x}" y="{y + 15 * i}" text-anchor="{anchor}">{esc(row)}</text>')

    def frame(self, x: float, y: float, w: float, h: float, label: str = "") -> None:
        self.out.insert(0, f'<rect class="dframe" x="{x}" y="{y}" width="{w}" height="{h}" rx="14"/>' + (f'<text class="dl" x="{x + 16}" y="{y + 20}">{esc(label)}</text>' if label else ""))
        self.low = max(self.low, y + h)

    def lanes(self, names: list[tuple[str, str, str]], steps: list[tuple[int, str, str, str]], links: dict[int, str] | None = None, step: int = 142) -> None:
        """A swimlane: who does what, left to right. Each step: (lane, icon, words, kind)."""
        links = links or {}
        top, band, cw = 6, 112, step - 26
        self.width = 132 + step * len(steps) + 4
        for i, (icon, name, kind) in enumerate(names):
            y = top + i * (band + 6)
            self.out.append(f'<rect class="dband" x="0" y="{y}" width="{self.width}" height="{band}" rx="10"/><g class="k-{kind}">{self.icon(icon, 60, y + 38, 22)}</g><text class="dt" x="60" y="{y + 86}" text-anchor="middle">{esc(name)}</text>')
        last = None
        for i, (lane, icon, words, kind) in enumerate(steps):
            x, y = 132 + i * step, top + lane * (band + 6) + 6
            rows = wrap(words, int(cw / 7.1))
            box = Box(x, y, cw, band - 12)
            self.out.append(f'<g class="k-{kind}"><rect class="dcard" x="{x}" y="{y}" width="{cw}" height="{band - 12}" rx="10"/><circle class="dnum" cx="{x + 13}" cy="{y + 13}" r="10.5"/><text class="dn" x="{x + 13}" y="{y + 17.5}">{i + 1}</text>'
                            f'{self.icon(icon, x + cw / 2 + 8, y + 21, 15)}' + "".join(f'<text class="ds" style="fill:var(--ink);font-size:13px" x="{x + cw / 2}" y="{y + 54 + 15 * k}" text-anchor="middle">{esc(r)}</text>' for k, r in enumerate(rows[:4])) + "</g>")
            if last is not None:
                self.go(last, box, kind="bad" if kind == "bad" else "good" if kind == "good" else "")
            last = box
        self.low = max(self.low, top + len(names) * (band + 6))

    def svg(self, standalone: bool = False) -> str:
        h = self.low + 10
        style = ""
        if standalone:
            style = f'<style>svg{{{ALL}--dfont:system-ui,"Segoe UI",Helvetica,Arial,sans-serif}}{RULES}</style><rect width="{self.width}" height="{h}" fill="#fff"/>'
        ns = ' xmlns="http://www.w3.org/2000/svg"' if standalone else ""
        return f'<svg{ns} role="img" aria-label="{esc(self.caption)}" viewBox="0 0 {self.width} {h}" width="{self.width}" height="{h}">{style}{"".join(self.out)}</svg>'


TWIN = ("city", "Twin", "twin")
GUARD = ("shield", "Guardian", "guardian")
BRAIN = ("brain", "City Brain", "brain")
GATE = ("lock", "Safety gate", "gate")
PERSON = ("person", "A person", "person")


def big_picture() -> D:
    d = D("big-picture", "The big picture: three teams, one city", "The Twin is the city and the Guardian judges every reading. The City Brain decides, and only its Safety gate can send an action back to the city. A live screen shows all of it.")
    twin = d.card(20, 150, "city", "Twin", "the simulated city, built by a partner team", "twin", 210)
    brain = d.card(515, 110, ["brain", "python"], "City Brain", "our layer: decides the response", "brain", 210, 220)
    guardian = d.card(1010, 150, "shield", "Guardian", "says whether each reading can be trusted", "guardian", 210)
    gate = d.card(530, 390, "lock", "Safety gate", "the only way out", "gate", 180)
    screen = d.card(960, 390, "monitor", "Live screen", "timeline and 3D brain", "person", 180)
    others = d.card(530, 0, "modelcontextprotocol", "Other teams", "", "store", 180, 90)
    d.line([(230, 190), (515, 190)], "sensor readings", at=(372, 180))
    d.line([(725, 190), (1010, 190)], "“can I trust this?”", at=(868, 180))
    d.line([(1010, 250), (725, 250)], "verdict", at=(868, 240))
    d.go(brain, gate, "every proposed action", at=(630, 362), anchor="start")
    d.line([(530, 440), (125, 440), (125, 280)], "signed actions", "gate", at=(330, 430))
    d.line([(725, 300), (1050, 300), (1050, 390)], "live events", at=(890, 290))
    d.line([(620, 90), (620, 110)])
    d.text(636, 104, "ask through tools", "start")
    d.low = 490
    return d


def inside() -> D:
    d = D("inside-the-brain", "Inside the Brain: the path of one reading", "A reading moves left to right through five parts, then gets one of two answers. Both answers must pass the Safety gate. What is kept afterwards can become a new instant rule.")
    y0, w = 10, 192
    s = d.card(10, y0, "eye", "Reads the city", "checks it, asks the Guardian", "brain", w, 138)
    f = d.card(255, y0, "chart", "Spots the unusual", "each sensor's own normal", "brain", w, 138)
    t = d.card(500, y0, "search", "Sorts what matters", "readings become incidents", "brain", w, 138)
    a = d.card(745, y0, "target", "Holds attention", "most urgent first", "brain", w, 138)
    p = d.card(990, y0, "tag", "Picks a department", "police, fire, roads, grid", "brain", 230, 138)
    for one, two in ((s, f), (f, t), (t, a), (a, p)):
        d.go(one, two)
    r = d.card(500, 210, "bolt", "Instant rule", "a clear case, in milliseconds", "brain", w, 138)
    team = d.card(865, 210, "agents", "Team of agents", "a harder case, reasons it through", "brain", 230, 138)
    d.go(t, r, "clear", at=(610, 190), anchor="start")
    d.line([(a.b[0], a.b[1]), (a.b[0], 180), (940, 180), (940, 210)], "", "gate", dash=True)
    d.line([(p.b[0], p.b[1]), (p.b[0], 180), (1020, 180), (1020, 210)], "harder", "gate", dash=True, at=(1045, 172), anchor="start")
    g = d.card(680, 410, "lock", "Safety gate", "the only way out", "gate", w, 138)
    tw = d.card(1010, 410, "city", "Acts in the city", "the Twin carries it out", "twin", 210, 138)
    d.line([(r.b[0], r.b[1]), (r.b[0], 380), (740, 380), (740, 410)])
    d.line([(team.b[0], team.b[1]), (team.b[0], 380), (810, 380), (810, 410)], "", "gate", dash=True)
    d.go(g, tw, "signed", "gate", at=(940, 468))
    m = d.card(255, 410, "book", "Remembers", "each closed incident", "brain", w, 138)
    sl = d.card(10, 410, "moon", "Learns in quiet time", "repeated plans become rules", "brain", w, 138)
    d.go(g, m, "what happened", at=(565, 468))
    d.line([(sl.r[0], 460), (m.l[0], 460)], "reads", at=(228, 450))
    d.line([(m.t[0], 410), (m.t[0], 279), (500, 279)], "a new rule, once it passes", at=(360, 269))
    d.low = 550
    return d


def two_answers() -> D:
    d = D("two-answers", "Two ways to answer", "One crime, two answers: a written rule sends the pursuit in tens of milliseconds, then a team of agents plans the perimeter. That took 0.1 to 0.5 s with the scripted stand-ins in our runs, and takes longer on a real model. Both stop at the same gate.")
    i = d.card(10, 110, "alert", "A suspect is seen", "the crime in scenario d3", "bad", 190)
    a = d.card(310, 0, "bolt", "Instant rule", "rule POL-001: pursue", "brain", 210)
    b = d.card(310, 200, "agents", "Team of agents", "Analyst, Tactician, Chief", "brain", 210)
    g = d.card(660, 110, "lock", "Safety gate", "the same checks for both", "gate", 190)
    x = d.card(990, 0, "unit", "One unit pursues", "fast, simple, certain", "twin", 220)
    y = d.card(990, 200, "route", "A full plan", "2 perimeter units, 1 alert", "twin", 220)
    d.go(i, a, "fast path")
    d.go(i, b, "slow path", at=(255, 300), anchor="middle")
    d.go(a, g, "tens of ms", at=(526, a.y + a.h / 2 - 8), anchor="start")
    d.go(b, g, "under a second", at=(526, b.y + b.h / 2 + 18), anchor="start")
    d.go(g, x, kind="gate")
    d.go(g, y, kind="gate")
    return d


def agent_team() -> D:
    d = D("agent-team", "The team of agents: models propose, code decides", "Each role can read but never act. Code checks the plan before the gate sees it. If a model call fails, a scripted stand-in takes that role and the scenario still passes, which is what happened with Groq's parse errors in the real-model runs.")
    a = d.card(10, 40, ["agents"], "Analyst", "builds the case, cites sources", "brain", 190)
    t = d.card(260, 40, ["agents"], "Tactician", "prepares options", "brain", 190)
    c = d.card(510, 40, ["agents"], "Chief", "chooses one option", "brain", 190)
    v = d.card(760, 40, "code", "Code check", "verify_case, verify_plan", "good", 190)
    g = d.card(1020, 40, "lock", "Safety gate", "still checks each action", "gate", 190)
    for one, two in ((a, t), (t, c), (c, v)):
        d.go(one, two)
    d.go(v, g, "if it holds", kind="good", at=(985, 74))
    tools = d.card(135, 240, "book", "Read-only tools", "city graph, playbooks, history", "store", 230)
    model = d.card(510, 240, "groq", "Real model", "or the scripted stand-in if the call fails", "store", 250)
    d.frame(0, 28, 712, a.h + 28, "")
    d.line([(tools.t[0], 240), (tools.t[0], 28 + a.h + 28)], "read only", at=(262, 226), dash=True)
    d.line([(model.t[0] - 30, 240), (model.t[0] - 30, 28 + a.h + 28)], "answers each role", at=(620, 226), anchor="middle", dash=True)
    bad = d.card(830, 240, "cross", "Plan refused", "nothing is sent", "bad", 190)
    d.go(v, bad, "if it breaks a rule", "bad", at=(868, 222), anchor="start")
    return d


def desks() -> D:
    d = D("department-desks", "Department desks: they pick zones, never words", "Fire, Ambulance and medical, Traffic control, Disaster response and Utilities each have an analyst and a chief. The chief picks which neighbouring zones to warn, code checks the choice, and the public wording is fixed in policy, so a model never writes a public message.")
    i = d.card(10, 70, "flame", "An incident", "reviewed again when a new source joins", "bad", 190)
    a = d.card(260, 70, "agents", "Desk analyst", "how serious is it?", "brain", 180)
    c = d.card(500, 70, "agents", "Desk chief", "warn which zones?", "brain", 180)
    v = d.card(740, 70, "code", "Code check", "within 2 hops, at most 3 zones", "good", 190)
    g = d.card(1000, 70, "lock", "Safety gate", "then the alert goes out", "gate", 200)
    d.go(i, a)
    d.go(a, c)
    d.go(c, v, "zone ids")
    d.go(v, g, "", "good")
    w = d.card(740, 270, "file", "Fixed wording", "written in policy.yaml", "store", 190)
    d.go(w, v, "the message", dash=True, at=(848, 256), anchor="start")
    for k, (icon, name) in enumerate((("flame", "Fire"), ("cross", "Ambulance"), ("signal", "Traffic"), ("drop", "Disaster"), ("code", "Utilities"))):
        d.card(10 + k * 250, 270, icon, name, "", "brain", 195, 112)
    d.text(320, 402, "five desks; Police has its own team of three")
    d.low = 410
    return d


def gate() -> D:
    d = D("safety-gate", "The Safety gate: eleven checks, in order", "Every action from every source passes these checks in this order. The first one that fails stops the action and records why. Only a call that passes all of them is signed and sent.")
    checks = [("code", "Follows the contract"), ("plug", "City can do this"), ("tag", "Department's remit"), ("check", "Incident still open"), ("shield", "Trusted verdict"), ("eye", "Enough witnesses"),
              ("person", "Person agreed, if high impact"), ("key", "Not already sent"), ("clock", "Not driven too often"), ("stop", "Not quarantined"), ("chart", "Within the budget")]
    start = d.card(10, 30, "bolt", "A proposed action", "from a rule, the team or a desk", "brain", 170, 148)
    cw, gap = 88, 7
    x = 210
    for k, item in enumerate(checks):
        icon, words = item[0], item[1]
        rows = wrap(words, 11)
        d.out.append(f'<g class="k-gate"><rect class="dcard" x="{x}" y="30" width="{cw}" height="148" rx="10"/>{d.icon(icon, x + cw / 2, 62, 19)}<circle class="dnum" cx="{x + 12}" cy="42" r="10"/><text class="dn" x="{x + 12}" y="46.5">{k + 1}</text>'
                     + "".join(f'<text class="ds" style="fill:var(--ink);font-weight:700" x="{x + cw / 2}" y="{104 + 15 * i}" text-anchor="middle">{esc(r)}</text>' for i, r in enumerate(rows)) + "</g>")
        x += cw + gap
    d.line([(180, 104), (210, 104)])
    d.frame(200, 16, 1052, 176, "")
    held = d.card(480, 230, "stop", "Held", "the first failed check is the reason on screen", "bad", 250)
    sent = d.card(980, 230, "stamp", "Signed and sent", "sent once, to the Twin", "good", 240)
    d.line([(605, 192), (605, 230)], "any check fails", "bad", at=(620, 214), anchor="start")
    d.line([(1100, 192), (1100, 230)], "all pass", "good", at=(1115, 214), anchor="start")
    d.width = 1262
    return d


def approval() -> D:
    d = D("human-approval", "A person's approval for high-impact actions", "Closing a valve or cutting a feeder waits for a person when approval is on. The approval is signed and fits only that exact call, expires and works once, and the call then goes back through the gate.")
    a = d.card(10, 40, "drop", "High-impact action", "a valve, a grid cut", "bad", 190)
    g = d.card(260, 40, "lock", "Safety gate", "holds it: needs a person", "gate", 190)
    w = d.card(510, 40, "clock", "Waiting", "kept across a restart", "store", 170)
    p = d.card(740, 40, "person", "A person decides", "with the approve permission", "person", 200)
    k = d.card(1010, 40, "key", "Signed approval", "exact call, expires, used once", "person", 210)
    d.go(a, g)
    d.go(g, w, "requested")
    d.go(w, p)
    d.go(p, k, "grants", "good")
    n = d.card(740, 260, "cross", "Denied", "nothing is sent", "bad", 200)
    d.go(p, n, "denies", "bad", at=(855, 228), anchor="start")
    s = d.card(1010, 260, "lock", "Gate checks again", "every later check runs", "gate", 210)
    d.go(k, s, kind="good")
    return d


def memory() -> D:
    d = D("memory", "Memory: two stores, and a fallback for both", "Neo4j holds the city graph and Qdrant the knowledge the agents search. A copy in memory is always there, so a database failure does not stop a decision: scenario b29 stops the vector store mid-run and still passes.")
    b = d.card(10, 110, "brain", "City Brain", "asks and records", "brain", 190)
    gm = d.card(330, 10, "networkx", "City graph", "in memory, always there", "store", 210)
    n = d.card(690, 10, "neo4j", "Neo4j", "the same graph, for queries and provenance", "store", 240)
    k = d.card(330, 210, "search", "Knowledge search", "playbooks, past cases", "store", 210)
    q = d.card(690, 210, "qdrant", "Qdrant", "vectors, hybrid search", "store", 240)
    f = d.card(1010, 210, "book", "Copy in memory", "takes over if Qdrant stops", "good", 210)
    d.go(b, gm, "where is it?")
    d.go(b, k, "what do we know?", at=(265, 262))
    d.go(gm, n, "mirrors every change", at=(615, 58))
    d.go(k, q, "first choice", at=(615, 258))
    d.go(q, f, "stops", "bad", at=(970, 258))
    d.low = 350
    return d


def learning() -> D:
    d = D("learning", "Learning in quiet time", "When the city is calm, the Brain looks for plans the team made the same way more than once. Each candidate faces six checks. A learned rule only saves deliberation: it still passes the Safety gate, and it is retired if the team starts planning differently.")
    e = d.card(10, 30, "book", "Closed incidents", "kept as stories", "brain", 180)
    m = d.card(240, 30, "search", "Find repeats", "same plan, more than once", "brain", 180)
    c = d.card(470, 30, "moon", "Six checks", "source, safety, limit, rehearsal, variants, Test Book", "gate", 230)
    r = d.card(780, 30, "bolt", "New instant rule", "can be rolled back", "good", 190)
    u = d.card(1030, 30, "lock", "Used next time", "still checked by the gate", "gate", 190)
    d.go(e, m)
    d.go(m, c)
    d.go(c, r, "all pass", "good")
    d.go(r, u, "", "good")
    n = d.card(470, 240, "cross", "Turned away", "with the reason", "bad", 230)
    d.go(c, n, "any fails", "bad", at=(600, 214), anchor="start")
    t = d.card(1030, 240, "agents", "Team disagrees later", "the rule is retired", "bad", 190)
    d.go(u, t, "checked over time", at=(1120, 222), anchor="end", dash=True)
    a = d.card(10, 240, "dial", "Academy", "tunes only 13 listed numbers, each with a range", "store", 240)
    d.text(130, 395, "a separate, bounded way to improve")
    d.low = 402
    return d


def engines() -> D:
    d = D("solvers", "Solvers: they propose, they do not act", "Engines work out the best move with mathematics, each off unless a scenario turns it on. A solver's answer comes with a certificate and goes through the same gate as anything else. If a solver fails, the Brain says so and uses the plain answer.")
    i = d.card(10, 70, "alert", "A hard choice", "two collisions, one close ambulance", "bad", 190)
    es = [("unit", "Dispatch", "who goes where"), ("route", "Clear road", "a green corridor"), ("eye", "Perimeter", "seal the suspect in"), ("bolt", "Load shed", "the cheapest grid cut"), ("waves", "Flood forecast", "time to the line")]
    boxes = []
    for k, (icon, name, note) in enumerate(es):
        col, row = k % 3, k // 3
        boxes.append(d.card(280 + col * 186, 10 + row * 130, icon, name, note, "brain", 172, 118))
    d.frame(268, 0, 570, 268, "")
    i.y = 60
    d.line([(200, 134), (268, 134)])
    c = d.card(890, 60, "stamp", "Answer + certificate", "how good, and against what", "good", 170)
    g = d.card(1090, 60, ["lock"], "Safety gate", "decides", "gate", 140)
    d.line([(838, 134), (890, 134)])
    d.go(c, g, "", "good")
    return d


def connect() -> D:
    d = D("connecting", "Connecting to any city", "The Brain talks to one small interface, and a different adapter fits each way a Twin can speak. A Twin with different field names needs only a config entry, which `brain onboard` proposes. `brain conformance` checks a partner against the contract.")
    a1 = d.card(10, 0, "modelcontextprotocol", "MCP Twin", "the default", "twin", 200)
    a2 = d.card(10, 160, "plug", "HTTP Twin", "plain REST", "twin", 200)
    a3 = d.card(10, 320, "mqtt", "MQTT Twin", "through a broker", "twin", 200)
    p = d.card(320, 150, "tag", "Name mapping", "a Twin's own words to the contract's", "brain", 230)
    b = d.card(650, 150, "brain", "City Brain", "one interface, whatever the Twin", "brain", 210)
    gu = d.card(1000, 0, "shield", "Guardian", "REST: a verdict per reading", "guardian", 210)
    oth = d.card(1000, 160, "modelcontextprotocol", "Other teams' agents", "call our 10 MCP tools", "store", 210)
    scr = d.card(1000, 320, "fastapi", "API and live feed", "REST and server-sent events", "person", 210)
    for x in (a1, a2, a3):
        d.go(x, p)
    d.go(p, b, "readings")
    d.go(b, gu, "ask", at=(930, 60))
    d.go(oth, b, "", dash=True)
    d.go(b, scr, "events", at=(930, 380))
    return d


def layers() -> D:
    d = D("security", "Security: what a message must get through", "Each layer stops a different attack, and all 22 red-team attacks were refused. The Guardian judges the data, the gate judges the action, and the log proves afterwards what happened.")
    items = [("lock", "Encrypted link", "TLS, when switched on"), ("key", "Token", "scoped, short-lived"), ("stamp", "Signature", "right key, not rotated out"), ("clock", "No replay", "time and one-use nonce"), ("code", "Clean fields", "safe ids, no injection"),
             ("shield", "Guardian", "trusted verdict"), ("lock", "Safety gate", "eleven checks"), ("chain", "Sealed log", "hash chain, signed head")]
    kinds = ["brain", "brain", "brain", "brain", "brain", "guardian", "gate", "good"]
    prev = None
    for k, (icon, name, note) in enumerate(items):
        box = d.card(10 + k * 154, 40, icon, name, note, kinds[k], 132, 166, num=k + 1)
        if prev:
            d.go(prev, box)
        prev = box
    bad = d.card(420, 250, "cross", "Refused at any step", "with its reason written to the log", "bad", 320)
    d.line([(580, 206), (580, 250)], "forged, replayed, hostile, out of scope", "bad", at=(595, 232), anchor="start")
    d.width = 1250
    return d


def proof() -> D:
    d = D("proof", "Proof: four ways to check a run", "Play a run's inputs back and the decisions must match. Change any line of a log and the chain shows it. Re-run the scenarios and every decision must equal the frozen record. Recorded model answers let the agents replay with no network.")
    rows = [("file", "Input journal", "every input kept", "store", "loop", "brain replay", "plays the inputs back", "check", "Same decisions", "exit 0 match, 1 difference"),
            ("chain", "Sealed log", "each event hashes the last, head signed", "store", "search", "brain audit verify", "walks the chain", "check", "Any changed line shows", "the chain breaks there"),
            ("book", "Test Book", "38 scenarios", "store", "scale", "brain baseline --check", "against a frozen record", "check", "Every decision as recorded", "or the check fails"),
            ("groq", "Agent cassette", "model answers on tape", "store", "agents", "Scenario in replay mode", "no network, no tokens", "check", "Same agent answers", "every time")]
    y = 0
    for icon, name, note, kind, icon2, name2, note2, icon3, name3, note3 in rows:
        a = d.card(60, y, icon, name, note, kind, 300, 120)
        b = d.card(470, y, icon2, name2, note2, "brain", 300, 120)
        c = d.card(880, y, icon3, name3, note3, "good", 300, 120)
        d.go(a, b)
        d.go(b, c)
        y += 132
    return d


def why() -> D:
    d = D("why", "“Why was that done?”", "Any decision or held action can be explained from the Brain's own log, with nothing invented: what it rested on, which check it passed or failed, and what would have changed it. The same explanation reaches four places.")
    l = d.card(10, 190, "chain", "The sealed log", "what really happened", "good", 200, 120)
    e = d.card(320, 190, "search", "Explanation", "built from the log, for one decision or hold", "brain", 250, 120)
    d.go(l, e)
    for k, (icon, name, note, kind) in enumerate((("monitor", "Side panel", "steps, gate, what would change it", "person"), ("brain", "Replay in the 3D brain", "camera visits each part (W key)", "person"), ("modelcontextprotocol", "Other teams' agents", "ask through an MCP tool", "store"), ("file", "Provenance export", "standard PROV format", "store"))):
        d.go(e, d.card(780, k * 126, icon, name, note, kind, 400, 114))
    return d


def deploy() -> D:
    d = D("deployment", "Running it: one Compose file", "make full starts five containers on one private network, and every published port is bound to this laptop. The same image runs the Brain and the two stand-in partners. A Groq key in .env puts real models behind the agents.")
    t = d.card(60, 20, "city", "twin", "stand-in, port 8765", "twin", 200, 130)
    g = d.card(60, 170, "shield", "guardian", "stand-in, port 8766", "guardian", 200, 130)
    b = d.card(460, 80, ["docker", "brain"], "brain", "port 8080: screen, API, /mcp, /metrics", "brain", 270, 160)
    n = d.card(930, 20, "neo4j", "neo4j", "city graph, in a volume", "store", 200, 130)
    q = d.card(930, 170, "qdrant", "qdrant", "knowledge, in a volume", "store", 200, 130)
    d.frame(30, 4, 1130, 312, "")
    d.text(595, 26, "private network")
    d.go(t, b, "readings", at=(330, 76))
    d.go(g, b, "verdicts", at=(330, 226))
    d.go(b, n, "mirrors", at=(830, 76))
    d.go(b, q, "searches", at=(830, 226))
    you = d.card(380, 345, "monitor", "Your browser", "http://127.0.0.1:8080", "person", 250, 118)
    d.line([(505, 345), (505, 240)], "this laptop only", at=(518, 332), anchor="start")
    key = d.card(780, 345, "file", ".env", "Groq key, Neo4j password", "store", 230, 118)
    d.line([(780, 404), (690, 404), (690, 240)], "secrets", dash=True, at=(702, 332), anchor="start")
    return d


def seeing() -> D:
    d = D("seeing", "Seeing it: one stream of events", "Everything the Brain does is one stream of timestamped events. The two screens are drawn from that stream and invent nothing, and the metrics and traces for operators come from the same place.")
    b = d.card(10, 190, "brain", "City Brain", "writes every event", "brain", 200, 120)
    s = d.card(320, 190, "chain", "The timeline", "CloudEvents, sealed", "good", 240, 120)
    d.go(b, s)
    for k, (icon, name, note, kind, word) in enumerate((("file", "Strip Board", "one reading, one line", "person", "live feed"), ("threedotjs", "3D canopy", "the brain over the city", "person", "live feed"), ("prometheus", "Prometheus and Grafana", "gate, solver, search", "store", "/metrics"), ("jaeger", "Jaeger", "one trace per reading", "store", "spans"))):
        box = d.card(780, k * 126, icon, name, note, kind, 400, 114)
        d.go(s, box)
        d.text(760, k * 126 + 50, word, "end")
    return d


def flow_crime() -> D:
    d = D("flow-crime", "Example run: a crime and a pursuit (d3)", "A robbery is seen, the Guardian vouches for it, a rule sends one unit in milliseconds, then the team adds a perimeter and an alert. After the arrest the Brain closes the incident and calls the spare units back.")
    d.lanes([TWIN, GUARD, BRAIN, GATE], [
        (0, "camera", "Camera sees a robbery; a citizen runs", "twin"),
        (1, "check", "Both readings trusted", "guardian"),
        (2, "search", "Incident opened. Police take it. Suspect, 0.82", "brain"),
        (3, "lock", "Pursuit passes all checks", "gate"),
        (0, "unit", "Unit p-01 pursues", "twin"),
        (2, "agents", "Team plans a tight perimeter", "brain"),
        (3, "lock", "2 units and 1 alert pass", "gate"),
        (0, "alert2", "Units posted, alert sent, arrest", "twin"),
        (2, "check", "Incident closed, 2 units recalled", "good"),
    ])
    return d


def flow_fake_flood() -> D:
    d = D("flow-fake-flood", "Example run: a fake flood (d2)", "Two gauges watch the harbour. One reads 0.3 m, the other 1.8 m, and the Guardian does not trust the second. The Brain still opens an incident, but the Safety gate refuses the warning and the valve call, and says why. When the honest gauge reads on, the incident closes.")
    d.lanes([TWIN, GUARD, BRAIN, GATE], [
        (0, "waves", "Gauge A reads 0.3 m; gauge B reads 1.8 m", "twin"),
        (1, "cross", "Gauge B: untrusted", "bad"),
        (2, "search", "Flood incident opened, evidence not trusted", "brain"),
        (3, "stop", "HELD: no trusted verdict stands behind the warning", "bad"),
        (3, "stop", "HELD: nor behind the valve call", "bad"),
        (0, "cross", "Nothing sent to the city", "bad"),
        (2, "check", "Gauge A reads 0.3 m again: incident closed", "good"),
    ], step=150)
    return d


def flow_flood_attack() -> D:
    d = D("flow-flood-attack", "Example run: a flood, an attack and a layer down (d4)", "The river rises while a forged robbery report arrives and a camera floods the Brain. The forecast warns the harbour before the line. The valve waits, because one trusted source is not two. Then the Guardian goes silent: the Brain says so once and carries on with low-impact alerts only.")
    d.lanes([TWIN, GUARD, BRAIN, GATE], [
        (0, "waves", "River gauge rising; a forged robbery report", "twin"),
        (1, "cross", "The robbery report: untrusted", "bad"),
        (2, "clock", "Forecast: about 10 s to the line. No police sent", "brain"),
        (3, "lock", "Early warning for the harbour passes", "gate"),
        (0, "waves", "The level crosses 1.0 m", "twin"),
        (2, "search", "Flood incident opened", "brain"),
        (3, "stop", "Valve HELD: needs 2 trusted sources, found 1", "bad"),
        (1, "stop", "The Guardian stops answering. Said once", "bad"),
        (0, "alert2", "Warnings still reach the harbour", "good"),
    ], step=150)
    return d


def flow_failure() -> D:
    d = D("flow-failures", "Example runs: when something breaks", "Each failure has a planned answer, and each is checked by a test or a scenario. The rule is the same throughout: lose a helper and carry on; lose trust and stop acting.")
    rows = [("shield", "Guardian stops answering", "d4", "guardian", "stop", "Low-impact actions only, and it says so once", "bad", "Safe: no high-impact action on unjudged data"),
            ("city", "Twin unreachable mid-pursuit", "tests", "twin", "loop", "Says it is degraded, asks again every 2 s", "brain", "Twin returns; the run carries on"),
            ("qdrant", "Vector store stops", "tests", "store", "book", "Copy in memory answers the search", "good", "Decisions do not change; the switch is logged"),
            ("groq", "A model call fails", "real runs", "store", "agents", "Scripted stand-in takes the role", "good", "Scenario still passes; fallback logged"),
            ("cross", "Attacker replays a reading", "red team", "bad", "clock", "Refused: seen before", "bad", "Nothing happens; refusal logged")]
    y = 0
    for icon, what, sid, kind, icon2, answer, kind2, end in rows:
        a = d.card(10, y, icon, what, sid, kind, 300, 112)
        b = d.card(420, y, icon2, answer, "", kind2, 380, 112)
        c = d.card(910, y, "check", end, "", "good" if kind2 != "bad" else "gate", 320, 112)
        d.go(a, b)
        d.go(b, c)
        y += 126
    return d


GLYPHS["target"] = '<circle cx="24" cy="24" r="18"/><circle cx="24" cy="24" r="9"/><circle cx="24" cy="24" r="2"/>'
SECTIONS = [
    ("The system", "What the parts are and how they connect.", [big_picture, inside]),
    ("Features", "One idea per drawing.", [two_answers, agent_team, desks, gate, approval, memory, learning, engines, connect, layers, proof, why, deploy, seeing]),
    ("Execution flows", "Real scenarios from the Test Book, step by step. The numbered path crosses a lane each time the work changes hands.", [flow_crime, flow_fake_flood, flow_flood_attack, flow_failure]),
]


def page() -> str:
    tokens = "".join(f"--{k}:{v};" for k, v in CSS_DARK.items())
    legend = "".join(f'<li><i style="background:var(--{k})"></i>{name}</li>' for k, name in (("twin", "the city (Twin)"), ("guardian", "the Guardian"), ("brain", "the City Brain"), ("gate", "the Safety gate"), ("person", "people and screens"), ("store", "stores and tools"), ("good", "went well"), ("bad", "stopped or failed")))
    body, nav, count = [], [], 0
    for title, intro, makers in SECTIONS:
        body.append(f'<section><h2>{esc(title)}</h2><p class="lede">{esc(intro)}</p>')
        for make in makers:
            d = make()
            count += 1
            (FILES / f"{count:02d}-{d.slug}.svg").write_text(d.svg(standalone=True))
            nav.append(f'<a href="#{d.slug}">{esc(d.title.split(":")[0] if not d.title.startswith("Example") else d.title.split(":")[1].strip())}</a>')
            body.append(f'<figure id="{d.slug}"><h3>{esc(d.title)}</h3><div class="scroll">{d.svg()}</div><figcaption>{esc(d.caption).replace("`", "")}</figcaption></figure>')
        body.append("</section>")
    return f"""<title>How the City Brain Works</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=B612:wght@400;700&display=swap">
<style>
/* An operator's manual for the system: plain cards on a quiet board, colour only for who owns each step. */
:root {{ {ALL} --dfont: "B612", system-ui, "Segoe UI", Helvetica, Arial, sans-serif; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ {tokens} color-scheme: dark; }} }}
:root[data-theme="dark"] {{ {tokens} color-scheme: dark; }}
body {{ background: var(--paper); color: var(--ink); font: 400 16px/1.5 var(--dfont); }}
main {{ max-width: 1280px; margin: 0 auto; padding-block: 40px 72px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }}
h1 {{ font-size: clamp(1.9rem, 4vw, 2.7rem); line-height: 1.15; margin: 0 0 .4rem; letter-spacing: -.01em; text-wrap: balance; }}
.lede {{ color: var(--ink2); margin: 0 0 1rem; max-width: 68ch; }}
h2 {{ font-size: 1.6rem; margin: 3rem 0 .3rem; padding-top: 1rem; border-top: 2px solid var(--ink); }}
h3 {{ font-size: 1.14rem; margin: 0 0 .7rem; text-wrap: balance; }}
figure {{ margin: 0 0 2.5rem; scroll-margin-top: 12px; }}
figcaption {{ color: var(--ink2); margin-top: .7rem; max-width: 80ch; }}
.scroll {{ overflow-x: auto; }}
.scroll svg {{ display: block; width: 100%; min-width: 860px; max-width: 100%; height: auto; }}
.legend {{ list-style: none; display: flex; flex-wrap: wrap; gap: .3rem 1.2rem; padding: 0; margin: 1.2rem 0; font-size: .92rem; color: var(--ink2); }}
.legend li {{ display: inline-flex; align-items: center; gap: .45rem; }}
.legend i {{ width: .8rem; height: .8rem; border-radius: 50%; display: inline-block; }}
nav {{ display: flex; flex-wrap: wrap; gap: .35rem; font-size: .86rem; }}
nav a {{ color: var(--ink); text-decoration: none; border: 1px solid var(--line); border-radius: 4px; padding: .12rem .5rem; background: var(--card); }}
nav a:hover {{ border-color: var(--ink2); }} nav a:focus-visible {{ outline: 2px solid var(--brain); outline-offset: 2px; }}
{RULES}
</style>
<main>
<h1>How the City Brain Works</h1>
<p class="lede">{count} drawings: what the system is, what each feature does, and what happens in a real run. The parts carry the same plain names as the live screen.</p>
<ul class="legend">{legend}</ul>
<nav aria-label="Diagrams">{"".join(nav)}</nav>
{"".join(body)}
</main>
"""


def main() -> None:
    FILES.mkdir(exist_ok=True)
    for old in FILES.glob("*.svg"):
        old.unlink()
    PAGE.write_text(page())
    print(f"wrote {PAGE} ({PAGE.stat().st_size // 1024} KB) and {len(list(FILES.glob('*.svg')))} SVG files in {FILES}")


if __name__ == "__main__":
    main()
