"""The City Brain's parts of the Phase 1 report, as one vector PDF and one self-contained HTML page.

    uv run python docs/report/build.py        # docs/report/report-city-brain.pdf, report-part2-city-brain.pdf and report-city-brain.html

Part 0 (the Brain in the triplet, 4 pages), Part 2 (the City Brain, 5 pages in the book's six subheadings) and Part 4 (the Test Book, 1 page),
ten A4 pages; Part 2 is also printed alone as report-part2-city-brain.pdf for the triplet's merged report. Every figure is drawn here as SVG
with the repository's icon set and the technology logos in docs/diagrams/logos/ (each logo belongs to its owner; none implies endorsement).
The numbers come from the repository: the Test Book, the frozen baseline, the suite, and real runs of t14 (timings), t13 and t15.
"""

from __future__ import annotations

import base64
import html
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "docs" / "diagrams"))
import simple_diagrams  # noqa: E402,F401  (adds the extra icons to GLYPHS)
from logo_architecture import GLYPHS, incident_flow, logo_uri, planner  # noqa: E402

FONTS = HERE / "fonts"  # Source Serif 4, Inter, IBM Plex Mono (OFL), see fonts/README.md
PDF, PAGE = HERE / "report-city-brain.pdf", HERE / "report-city-brain.html"
PART2 = HERE / "report-part2-city-brain.pdf"  # Part 2 alone, five pages, for the triplet's merged report

INK, INK2, MUTED, RULE, BOARD, STRIP = "#111417", "#3F464A", "#636B6F", "#AEB5AF", "#E6E9E4", "#FFFFFF"
BLUE, GOOD, WARN, BAD = "#1B49CF", "#18794A", "#A85F00", "#C0311E"
WASH = {BLUE: "#EEF2FC", GOOD: "#EAF4EE", WARN: "#FBF1E2", BAD: "#FBECE9", INK: "#F2F4F1", MUTED: "#F2F4F1"}
SANS, MONO = "Inter, sans-serif", "'IBM Plex Mono', monospace"


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def T(x, y, s, size=11, weight=400, fill=INK, anchor="start", family=SANS, rotate=None) -> str:
    turn = f" transform='rotate({rotate} {x} {y})'" if rotate is not None else ""
    return f"<text x='{x}' y='{y}' font-size='{size}' font-weight='{weight}' fill='{fill}' text-anchor='{anchor}' font-family=\"{family}\"{turn}>{esc(s)}</text>"


def LINES(x, y, rows, size=10.5, gap=13.5, fill=INK2, anchor="start", weight=400, family=SANS) -> str:
    return "".join(T(x, y + i * gap, r, size, weight, fill, anchor, family) for i, r in enumerate(rows))


def R(x, y, w, h, fill=STRIP, stroke=INK, sw=1, r=7, dash=None) -> str:
    d = f" stroke-dasharray='{dash}'" if dash else ""
    return f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='{r}' fill='{fill}' stroke='{stroke}' stroke-width='{sw}'{d}/>"


def ICON(name, cx, cy, size=24, color=BLUE, sw=2.6) -> str:
    k = size / 48
    return (f"<g transform='translate({cx - size / 2:.1f} {cy - size / 2:.1f}) scale({k:.3f})' fill='none' stroke='{color}' stroke-width='{sw}' "
            f"stroke-linecap='round' stroke-linejoin='round'>{GLYPHS[name]}</g>")


def BADGE(name, cx, cy, size=34, color=BLUE) -> str:
    return f"<circle cx='{cx}' cy='{cy}' r='{size / 2}' fill='{WASH.get(color, '#F2F4F1')}' stroke='{color}' stroke-width='1.3'/>" + ICON(name, cx, cy, size * 0.62, color)


def LOGO(name, x, y, h=18) -> tuple[str, float]:
    uri, ratio = logo_uri(name)
    w = h * ratio
    tile = R(x, y, w + 8, h + 8, STRIP, "#D5DCE1", 1, 4)
    return tile + f"<image href='{uri}' x='{x + 4}' y='{y + 4}' width='{w:.1f}' height='{h}' preserveAspectRatio='xMidYMid meet'/>", w + 8


def LOGOS(names, x, y, h=16, gap=4) -> str:
    out, cx = [], x
    for n in names:
        s, w = LOGO(n, cx, y, h)
        out.append(s)
        cx += w + gap
    return "".join(out)


def NODE(x, y, w, h, title, sub=(), icon=None, tone=BLUE, logos=(), accent=False, dashed=False) -> str:
    out = [R(x, y, w, h, WASH.get(tone, STRIP) if accent else STRIP, tone, 2 if accent else 1.2, 7, "4 3" if dashed else None)]
    tx = x + 10
    if icon:
        out.append(ICON(icon, x + 20, y + 20, 20, tone))
        tx = x + 36
    out.append(T(tx, y + 24, title, 11, 700, tone if accent else INK))
    out.append(LINES(x + 10, y + 42, sub, 9.3, 12, INK2))
    if logos:
        total = sum(logo_uri(n)[1] * 14 + 12 for n in logos)
        out.append(LOGOS(logos, x + w - 8 - total, y + 8, 14, 4) if w >= 300 else LOGOS(logos, x + 10, y + h - 26, 14, 4))
    return "".join(out)


_MARK: set[str] = set()


def ARROW(points, tone=INK, label=None, lx=None, ly=None, dash=None, width=1.4, both=False, anchor="middle", size=9.5) -> str:
    _MARK.add(tone)
    d = "M" + "L".join(f"{x} {y}" for x, y in points)
    ends = f" marker-end='url(#m{tone[1:]})'" + (f" marker-start='url(#m{tone[1:]})'" if both else "")
    dd = f" stroke-dasharray='{dash}'" if dash else ""
    out = f"<path d='{d}' fill='none' stroke='{tone}' stroke-width='{width}'{dd}{ends}/>"
    if label:
        out += T(lx, ly, label, size, 400, tone, anchor)
    return out


def SVG(w, h, body, label) -> str:
    tones = [BLUE, GOOD, WARN, BAD, INK, MUTED]
    defs = "".join(f"<marker id='m{t[1:]}' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='6.5' markerHeight='6.5' orient='auto-start-reverse'>"
                   f"<path d='M0 0L10 5L0 10z' fill='{t}'/></marker>" for t in tones)
    return f"<svg viewBox='0 0 {w} {h}' role='img' aria-label='{esc(label)}' xmlns='http://www.w3.org/2000/svg'><defs>{defs}</defs>{body}</svg>"


# --------------------------------------------------------------------------------------------------- figure 1


def fig_architecture() -> str:
    b = []
    # Twin
    b.append(R(0, 30, 150, 624, STRIP, INK, 1.4, 9, "5 3"))
    b.append(BADGE("city", 75, 64, 38, MUTED) + T(75, 100, "Twin", 13, 700, INK, "middle") + T(75, 113, "a simulated city", 9.5, 400, MUTED, "middle"))
    b.append(T(14, 150, "sends, signed", 9.5, 700, MUTED))
    for i, (ic, t) in enumerate((("camera", "traffic camera"), ("drop", "water level"), ("bolt", "power load"), ("waves", "air quality"), ("phone", "emergency call"), ("person", "citizen activity"), ("unit", "unit status"))):
        b.append(ICON(ic, 24, 172 + i * 28, 18, MUTED, 2.4) + T(40, 176 + i * 28, t, 10, 400, INK2))
    b.append(T(14, 394, "offers actuators", 9.5, 700, MUTED))
    for i, (ic, t) in enumerate((("unit", "dispatch_unit"), ("alert", "broadcast_alert"), ("signal", "set_signal_phase"), ("drop", "set_valve_state"), ("bolt", "set_grid_connection"))):
        b.append(ICON(ic, 24, 416 + i * 28, 18, BLUE, 2.4) + T(40, 420 + i * 28, t, 9.5, 400, INK2, family=MONO))
    # Guardian
    b.append(R(630, 130, 150, 262, STRIP, INK, 1.4, 9, "5 3"))
    b.append(BADGE("shield", 705, 164, 38, GOOD) + T(705, 200, "Guardian", 13, 700, INK, "middle") + T(705, 213, "trust and security", 9.5, 400, MUTED, "middle"))
    b.append(LINES(705, 246, ["a verdict on", "every reading", "", "a quarantine list", "of actuators", "", "contract 1.0: audits", "valve, grid, signal", "and dispatch calls"], 10, 14, INK2, "middle"))
    # Brain frame
    b.append(R(190, 14, 420, 656, BOARD, INK, 2, 12))
    b.append(T(204, 34, "City Brain layer", 13, 700) + T(594, 34, "every arrow is an event on the timeline", 9, 400, MUTED, "end"))
    X1, X2, X3, W3, WF = 204, 332, 460, 126, 382
    y1, y2, y3, y4, yg, y6 = 46, 124, 232, 320, 436, 512
    b.append(NODE(X1, y1, WF, 62, "Ports and adapters", ["MCP, HTTP or MQTT from the Twin; REST to the Guardian (contract 1.0)"], "plug", BLUE, ("modelcontextprotocol", "mqtt")))
    b.append(NODE(X1, y2, 120, 92, "Knowledge", ["39 procedures", "hybrid search"], "book", MUTED, ("qdrant",)))
    b.append(NODE(X2, y2, 120, 92, "City graph", ["zones, units,", "incidents"], "db", MUTED, ("neo4j", "networkx")))
    b.append(NODE(X3, y2, W3, 92, "Perception", ["signature, replay,", "demographics dropped"], "shield", GOOD))
    b.append(NODE(X1, y3, 120, 70, "Workspace", ["two incidents at a time;", "departments bid"], "eye", INK))
    b.append(NODE(X2, y3, 120, 70, "Triage", ["detectors open", "an incident"], "route", INK))
    b.append(NODE(X3, y3, W3, 70, "Forward models", ["prediction error,", "level forecast"], "dial", GOOD))
    b.append(NODE(X1, y4, 120, 100, "Reflex rules", ["milliseconds,", "no model"], "bolt", INK))
    b.append(NODE(X2, y4, 120, 100, "Teams", ["Police: 3 agents", "5 desks of two"], "agents", INK, ("langgraph", "groq")))
    b.append(NODE(X3, y4, W3, 100, "Solvers", ["dispatch, perimeter,", "shed, forecast,", "corridor"], "scale", WARN, ("ortools",)))
    b.append(NODE(X1, yg, WF, 62, "Safety gate: the only way out", ["11 checks, a person approves a valve or the grid"], "lock", BLUE, accent=True))
    b.append(NODE(X1, y6, 120, 82, "Memory", ["episodes, sleep,", "learned reflexes, tuning"], "loop", GOOD))
    b.append(NODE(X2, y6, 120, 82, "Log and why", ["hash-chained log,", "explanations"], "chain", MUTED, ("cloudevents",)))
    b.append(NODE(X3, y6, W3, 82, "Screen and API", ["timeline, 3D view,", "approvals, alerts"], "monitor", MUTED, ("fastapi",)))
    b.append(T(204, 626, "Model health: a rejected key or spent quota sends the teams to", 9.3, 400, INK2) + T(204, 639, "their scripted stand-ins at once. A person is asked when no playbook", 9.3, 400, INK2) + T(204, 652, "fits, an alarm is unknown, or an incident stalls.", 9.3, 400, INK2))
    # arrows
    b.append(ARROW([(150, 77), (204, 77)], INK, "readings", 170, 70, size=8.8))
    b.append(ARROW([(523, 108), (523, y2)], INK))
    b.append(ARROW([(586, 168), (630, 168)], GOOD, "verdict", 608, 161, both=True, size=8.8))
    b.append(ARROW([(460, 170), (452, 170)], INK))
    b.append(ARROW([(523, y2 + 92), (523, y3)], INK))
    b.append(ARROW([(460, y3 + 35), (452, y3 + 35)], GOOD))
    b.append(ARROW([(332, y3 + 35), (324, y3 + 35)], INK))
    b.append(ARROW([(264, y3 + 70), (264, y4)], INK))
    b.append(ARROW([(380, y3 + 70), (380, y4)], INK))
    b.append(ARROW([(523, y3 + 70), (523, y4)], WARN, dash="4 3"))
    b.append(ARROW([(460, y4 + 50), (452, y4 + 50)], WARN, dash="4 3"))
    b.append(ARROW([(264, y4 + 100), (264, yg)], BLUE, width=1.8))
    b.append(ARROW([(392, y4 + 100), (392, yg)], BLUE, width=1.8))
    b.append(ARROW([(392, yg + 62), (392, y6)], INK))
    b.append(ARROW([(332, y6 + 41), (324, y6 + 41)], GOOD, dash="4 3"))
    b.append(ARROW([(452, y6 + 41), (460, y6 + 41)], INK))
    b.append(ARROW([(204, yg + 31), (150, yg + 31)], BLUE, None, width=2) + T(170, yg + 16, "signed", 8.8, 400, BLUE, "middle") + T(170, yg + 26, "call", 8.8, 400, BLUE, "middle"))
    b.append(ARROW([(586, yg + 31), (705, yg + 31), (705, 392)], GOOD, "quarantined?", 646, yg + 24, both=True, size=8.8))
    b.append(ARROW([(204, y6 + 41), (197, y6 + 41), (197, y4 + 50), (204, y4 + 50)], GOOD, dash="4 3"))
    # legend
    ly = 686
    b.append(ARROW([(0, ly), (30, ly)], BLUE, width=2) + T(36, ly + 4, "signed calls", 10.5, 400, INK2))
    b.append(ARROW([(120, ly), (150, ly)], WARN, dash="4 3") + T(156, ly + 4, "solver answers go into the team's brief", 10.5, 400, INK2))
    b.append(ARROW([(380, ly), (410, ly)], GOOD, dash="4 3") + T(416, ly + 4, "learning and trust", 10.5, 400, INK2))
    b.append(ARROW([(540, ly), (570, ly)], INK) + T(576, ly + 4, "data", 10.5, 400, INK2))
    # v1 only: the Guardian team's Guardian is also fed by the Twin. The arrow runs above the Brain, so the figure is shifted down to make room.
    link = ARROW([(75, 60), (75, 20), (705, 20), (705, 160)], INK, "contract 1.0: the Twin also feeds the Guardian, which forwards no reading to the Brain and audits four kinds of call", 390, 12, dash="4 3", size=10.5, both=True)
    return SVG(780, 730, f"<g transform='translate(0,30)'>{''.join(b)}</g>" + link, "Global architecture: Twin, City Brain and Guardian")



# --------------------------------------------------------------------------------------------------- figure: the line between logic and partners


def fig_interop() -> str:
    b = []
    b.append(R(0, 10, 100, 152, STRIP, INK, 1.4, 9, "5 3") + BADGE("city", 50, 40, 34, MUTED) + T(50, 76, "Twin", 12.5, 700, INK, "middle") + LINES(50, 94, ["any engine that", "speaks the card"], 9, 12, MUTED, "middle"))
    b.append(R(680, 10, 100, 152, STRIP, INK, 1.4, 9, "5 3") + BADGE("shield", 730, 40, 34, GOOD) + T(730, 76, "Guardian", 12.5, 700, INK, "middle") + LINES(730, 94, ["any service that", "issues a verdict"], 9, 12, MUTED, "middle"))
    b.append(NODE(130, 10, 138, 152, "Twin adapters", ["readings in, signed", "calls out; one class", "per protocol: MCP", "(default), HTTP, MQTT", "", "TLS and retries", "stay here"], "plug", BLUE, ("modelcontextprotocol", "mqtt")))
    b.append(NODE(512, 10, 138, 152, "Guardian adapter", ["contract 1.0: asks the", "verdict by sensor and", "sequence number;", "sends valve, grid,", "signal and dispatch", "calls to be audited", "no verdict, no action"], "plug", BLUE))
    b.append(R(286, 10, 208, 152, BOARD, INK, 2, 12) + T(298, 32, "Decision logic", 12, 700) + LINES(298, 48, ["perception, triage, workspace,", "teams, solvers, safety gate"], 9.3, 12, INK2))
    b.append(NODE(298, 78, 184, 76, "Checks on entry", ["schema, contract version,", "signature, replay, id pattern;", "a refusal has a code and a reason"], "shield", GOOD, accent=True))
    for x, name in ((268, "TwinPort"), (494, "GuardianPort")):
        b.append(R(x, 10, 18, 152, WASH[BLUE], BLUE, 1.6, 4) + T(x + 9, 86, name, 9.3, 700, BLUE, "middle", MONO, rotate=-90))
    b.append(ARROW([(100, 58), (130, 58)], INK) + ARROW([(650, 58), (680, 58)], INK))  # readings in; verdict requests and audited calls out
    b.append(ARROW([(130, 118), (100, 118)], BLUE, width=1.8) + ARROW([(680, 118), (650, 118)], GOOD))  # signed calls to the Twin; signed verdicts back
    b.append(NODE(130, 192, 220, 78, "config/partners.yaml", ["address, adapter, secret names,", "renames and units per partner", "no partner address in the logic"], "file", WARN, accent=True))
    b.append(ARROW([(200, 192), (200, 162)], WARN, dash="4 3", width=1.6) + ARROW([(330, 192), (330, 176), (581, 176), (581, 162)], WARN, dash="4 3", width=1.6))
    b.append(NODE(366, 192, 280, 78, "The Interface Card and the contract", ["INTERFACE.md, JSON Schemas, an example of every", "message; JSON, HMAC-SHA256 or Ed25519;", "CloudEvents 1.0 for the timeline"], "tag", BLUE))
    b.append(NODE(662, 192, 118, 78, "Conformance", ["brain conformance", "tests a real partner"], "check", GOOD))
    # The Twin feeds the Guardian too, and the Guardian forwards the calls it audited: the same wiring as Figure 2.1, outside the Brain.
    top = ARROW([(50, 36), (50, 14), (730, 14), (730, 36)], MUTED, dash="4 3", both=True) + T(390, 9, "contract 1.0: the Twin also sends its readings to the Guardian; the Guardian forwards the calls it audited to the Twin", 8.8, 400, MUTED, "middle")
    return SVG(780, 306, top + f"<g transform='translate(0,26)'>{''.join(b)}</g>", "The line between the Brain's logic and its partners")


# --------------------------------------------------------------------------------------------------- figure 2


def fig_trace() -> str:
    lanes = [("Twin", "city", MUTED), ("Guardian", "shield", GOOD), ("Perception", "eye", GOOD), ("Triage, workspace", "route", INK),
             ("Reflex", "bolt", INK), ("Police team", "agents", INK), ("Solvers", "scale", WARN), ("Gate", "lock", BLUE)]
    cx = [52 + i * 97 for i in range(8)]
    b = []
    for (name, ic, tone), x in zip(lanes, cx):
        b.append(BADGE(ic, x, 22, 30, tone) + T(x, 52, name, 9.5, 700, INK, "middle"))
        b.append(f"<path d='M{x} 60V520' stroke='{RULE}' stroke-width='1' stroke-dasharray='3 4'/>")

    def step(y, a, c, label, tone=INK, ms=None, dash=None, both=False):
        out = ""
        if a == c:
            out += R(cx[a] - 46, y - 11, 92, 22, WASH.get(tone, STRIP), tone, 1.1, 5) + LINES(cx[a], y - 1, [label[0]], 8.6, 0, INK, "middle") + (LINES(cx[a], y + 8, [label[1]], 8.2, 0, INK2, "middle") if len(label) > 1 else "")
        else:
            lo, hi = sorted((cx[a], cx[c]))
            out += ARROW([(cx[a] + (4 if c > a else -4), y), (cx[c] - (4 if c > a else -4), y)], tone, None, dash=dash, width=1.6, both=both)
            out += T((lo + hi) / 2, y - 4, label, 8.8, 400, tone, "middle")
        if ms is not None:
            out += T(2, y + 3, ms, 8.6, 400, MUTED, family=MONO)
        return out

    y = 82
    rows = [
        (0, 2, "cctv_anomaly robbery 0.93, signed", BLUE, "+0 ms", None, False),
        (2, 1, "judge this reading", GOOD, None, None, False),
        (1, 2, "trusted", GOOD, "+5 ms", None, False),
        (3, 3, ["inc-0001 crime", "zone-07, seat 1"], INK, "+5 ms", None, False),
        (0, 2, "citizen sighting: 18 km/h away", BLUE, "+457 ms", None, False),
        (3, 3, ["suspect cit-88213", "score 0.82"], INK, "+466 ms", None, False),
        (3, 4, "rule POL-001", INK, None, None, False),
        (4, 7, "dispatch_unit pursuit", BLUE, "+471 ms", None, False),
        (7, 1, "quarantined?", GOOD, None, "3 3", True),
        (7, 0, "signed call", BLUE, "+473 ms", None, False),
        (0, 7, "dispatched unit-p-01", INK, "+480 ms", None, False),
        (3, 5, "recruit the team", INK, None, None, False),
        (5, 5, ["Analyst: pursue", "Tactician: options"], INK, "+483 ms", None, False),
        (5, 6, "perimeter check", WARN, None, "4 3", False),
        (6, 5, "2 units would hold", WARN, "+588 ms", "4 3", False),
        (5, 5, ["Chief: perimeter", "verified by code"], INK, "+588 ms", None, False),
        (5, 7, "contain x2 and an alert", BLUE, "+594 ms", None, False),
        (7, 0, "3 signed calls, 3 results", BLUE, "+616 ms", None, False),
        (0, 2, "units report; suspect caught", BLUE, "+15.6 s", None, False),
        (3, 3, ["incident closed", "apprehended"], INK, None, None, False),
        (4, 7, "recall_unit x2", BLUE, "+15.6 s", None, False),
    ]
    for a, c, lab, tone, ms, dash, both in rows:
        b.append(step(y, a, c, lab, tone, ms, dash, both))
        y += 22.5
    return SVG(780, 548, "".join(b), "Crime and pursuit traced across the layers with measured times")


# --------------------------------------------------------------------------------------------------- figure 7 gate


def gate_table() -> str:
    """The safety gate's eleven checks in the order gate/__init__.py runs them. Quoted reasons are from the canonical logs; the rest are the code's
    templates, placeholders in italics."""
    rows = [
        ("schema", "the call does not match the contract", "call does not match the contract: <i>field error</i>"),
        ("capability", "the Twin does not list the action", "the Twin does not expose <i>action</i>"),
        ("allowlist", "the department may not use the action", "department <i>name</i> may not call <i>action</i>"),
        ("incident open", "the incident is closed (recalls still pass)", "incident <i>id</i> is closed (<i>outcome</i>)"),
        ("trust_ref", "no trusted, unexpired verdict covers its evidence", "&ldquo;no Guardian verdict referenced&rdquo;"),
        ("evidence", "too few trusted sources for its impact level", "&ldquo;high-impact action needs 2 independent trusted sources, found 1 (wl-01-01)&rdquo;"),
        ("human approval", "a valve or grid call has no signed approval yet", "a high-impact action needs a person&rsquo;s approval&hellip;"),
        ("idempotency", "the same call was already issued", "already issued for <i>key</i>"),
        ("cooling gap", "the actuator was driven too recently", "<i>actuator</i> was last driven <i>n</i> s ago; the minimum gap&hellip;"),
        ("quarantine", "the device is quarantined or cannot be checked", "&ldquo;the Guardian has quarantined police-dispatch-05&rdquo;"),
        ("budget", "6 actions per incident, or 20 per minute", "incident <i>id</i> reached its limit of 6 actions"),
    ]
    body = "".join(f"<tr><td>{k}</td><td>{name}</td><td>{when}</td><td>{why}</td></tr>" for k, (name, when, why) in enumerate(rows, 1))
    return ("<table class='gate'><tr><th style='width:4%'>#</th><th style='width:14%'>Check</th><th style='width:37%'>Refuses the call when</th>"
            f"<th>Reason logged</th></tr>{body}</table>")


# --------------------------------------------------------------------------------------------------- figure 9 stack


def stack_table() -> str:
    """The stack grouped by job, each group with its logos and the reason for the choice."""
    rows = [
        (("python", "uv", "pydantic"), "Language and contracts", "Python 3.12, uv, Pydantic",
         "One language for rules, agents and solvers; locked builds; every message a typed model that validates itself."),
        (("langgraph", "langchain", "groq"), "Agents", "LangGraph, LangChain, Groq",
         "Graphs that pause, resume and checkpoint, as the agents and human approval need; a scripted team answers when no model is reachable."),
        (("ortools", "numpy", "networkx"), "Solvers", "OR-Tools, NumPy, NetworkX",
         "Proven solvers with a certificate for answers that must be exact; the Kalman forecast; the city graph in memory."),
        (("neo4j", "qdrant", "sqlite"), "Storage", "Neo4j, Qdrant, SQLite",
         "&ldquo;Why was this unit sent?&rdquo; in one graph query; hybrid search over 39 procedures; approvals and checkpoints. No decision waits on them."),
        (("modelcontextprotocol", "fastapi", "mqtt", "cloudevents"), "Interfaces", "MCP, FastAPI, MQTT, CloudEvents",
         "MCP gives the Twin&rsquo;s tools schemas and discovery; REST is one question, one answer per verdict; SSE is one-way, replayable, library-free."),
        (("docker", "opentelemetry", "threedotjs", "pytest"), "Operations", "Docker, OpenTelemetry, three.js, pytest",
         "One command starts the whole city; spans follow a reading through every step; the screen works offline; 1,114 tests."),
    ]
    out = []
    for logos, job, names, why in rows:
        imgs = "".join(f"<img src='{logo_uri(name)[0]}' alt='' style='height:4mm;width:{4 * min(logo_uri(name)[1], 3.2):.1f}mm'>" for name in logos)
        out.append(f"<tr><td><span class='logos'>{imgs}</span></td><td><b>{job}</b><br>{names}</td><td>{why}</td></tr>")
    return ("<table class='stack'><tr><th style='width:16%'></th><th style='width:24%'>Job and technology</th><th>Why</th></tr>"
            + "".join(out) + "</table>")


def fig_failures() -> str:
    cards = [
        ("shield", GOOD, "Guardian silent", "no action on a reading it has not judged; a call still needs a trusted, unexpired verdict", "t15"),
        ("city", MUTED, "Twin goes away", "one degraded, state kept, nothing sent twice, one recovered", "unit test"),
        ("key", BAD, "Model outage", "named at the first failure; scripted team answers at once", "llm-check"),
        ("alert", WARN, "Unknown alarm", "no incident, a person is asked once", "unit test"),
        ("lock", BLUE, "Forged or replayed", "refused with a code; the screen ignores it", "redteam"),
    ]
    b = []
    for i, (ic, tone, title, text, sc) in enumerate(cards):
        x = i * 157
        b.append(R(x, 0, 148, 142, WASH[tone], tone, 1.2, 9) + BADGE(ic, x + 26, 28, 32, tone) + T(x + 48, 32, title, 9.6, 700, INK))
        words, lines, cur = text.split(), [], ""
        for wd in words:
            if len(cur) + len(wd) + 1 > 27:
                lines.append(cur)
                cur = wd
            else:
                cur = (cur + " " + wd).strip()
        lines.append(cur)
        b.append(LINES(x + 10, 60, lines, 9, 12, INK2) + T(x + 10, 132, sc, 8.6, 700, tone, family=MONO))
    return SVG(780, 142, "".join(b), "What each failure does")


# --------------------------------------------------------------------------------------------------- the pages

CSS = """
@page{size:A4;margin:0}
*{box-sizing:border-box}
html,body{margin:0;background:#fff;color:#16191B;font:400 9.1pt/1.38 'Source Serif 4',Georgia,serif;font-kerning:normal}
.page{width:210mm;height:297mm;padding:12mm 15mm 13mm;position:relative;break-after:page;overflow:hidden}
.page:last-child{break-after:auto}
.top,.foot,h1,h2,h3,table,.cap,.meta{font-family:Inter,Arial,sans-serif}
.top{display:flex;justify-content:space-between;align-items:baseline;border-bottom:.5pt solid #16191B;padding-bottom:1.6mm;margin-bottom:5mm;font-size:7.4pt;color:#4A5156}
.top b{font-weight:600;color:#16191B}
.foot{position:absolute;left:15mm;right:15mm;bottom:6.5mm;display:flex;justify-content:space-between;font-size:7.4pt;color:#4A5156}
h1{font-size:17pt;font-weight:600;letter-spacing:-.01em;margin:0 0 1.2mm;line-height:1.15}
h2{font-size:11.5pt;font-weight:600;margin:5mm 0 1.6mm;line-height:1.2}
h3{font-size:9.6pt;font-weight:600;margin:3.4mm 0 1mm;line-height:1.25}
h4{font:600 8.6pt/1.25 Inter,Arial,sans-serif;color:#2B3134;margin:3mm 0 .8mm}
h1+h2,.top+h2{margin-top:0}
.meta{font-size:7.8pt;color:#4A5156;margin:0 0 4mm;line-height:1.45}
p{margin:0 0 2mm;hyphens:auto}
.lede{font-size:inherit}
svg{width:100%;height:auto;display:block;margin:2.5mm 0 1.5mm}
.cap{font-size:7.6pt;line-height:1.4;color:#3A4045;margin:0 0 3.5mm}
.cap b{font-weight:600;color:#16191B}
table{border-collapse:collapse;width:100%;font-size:7.7pt;line-height:1.38;margin:1.5mm 0 3mm;font-variant-numeric:tabular-nums;border-top:1pt solid #16191B;border-bottom:1pt solid #16191B}
th{text-align:left;font-weight:600;padding:1.2mm 1.6mm 1mm;border-bottom:.5pt solid #16191B;vertical-align:bottom}
td{padding:1mm 1.6mm;vertical-align:top;border-bottom:.4pt solid #DADDD9}
tr:last-child td{border-bottom:0}
code{font-family:'IBM Plex Mono',monospace;font-size:.86em;color:#2B3134}
table code{font-size:.92em}
.stack td{vertical-align:middle}.stack .logos{display:flex;gap:1.6mm;align-items:center}
pre.log{font:400 6.9pt/1.45 'IBM Plex Mono',monospace;color:#2B3134;margin:1.2mm 0 3mm;padding:1.8mm 2.4mm;border-left:.5pt solid #16191B;border-top:.5pt solid #DADDD9;border-bottom:.5pt solid #DADDD9;white-space:pre}
.gate,.goals{font-size:7.3pt}.goals td{padding:.8mm 1.6mm}.gate{font-size:7.3pt}.gate td{padding:.8mm 1.6mm}.gate td:first-child{color:#4A5156}.gate td:nth-child(2){font-weight:600;white-space:nowrap}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:6mm}
.rule{display:grid;grid-template-columns:7mm 1fr;gap:2mm;align-items:start;margin-bottom:1.6mm}
.rule svg{width:7mm;margin:0}.rule p{margin:0}
ol.items,ul.items{margin:1mm 0 2.5mm;padding-left:5mm}ol.items li,ul.items li{margin:0 0 1.2mm;padding-left:1mm}
@media screen{html,body{background:#CFD3D0}.page{margin:8mm auto;box-shadow:0 1px 6px rgba(17,20,23,.2);background:#fff}}
.pill{display:inline-block;font-size:7.4pt;font-weight:600;border:.5pt solid currentColor;padding:0 1.4mm;margin-right:1mm}
"""


def rejection_rows() -> str:
    """Bad readings run through the Brain's own Perception, so the table is what a partner would really be told."""
    import copy
    import json

    from brain.contracts import CONTRACT_VERSION
    from brain.contracts.signing import sign
    from brain.perception import ContractError, Perception

    secret = "development-secret"
    plain = json.loads((ROOT / "contracts/examples/reading.water_level.json").read_text())
    plain.pop("provenance", None)
    good = sign(copy.deepcopy(plain), secret, "twin")

    def edited(**changes):
        raw = copy.deepcopy(good)
        for key, value in changes.items():
            raw.pop(key, None) if value is None else raw.__setitem__(key, value)
        return raw

    def tampered():
        raw = copy.deepcopy(good)
        raw["value"]["level_m"] = 9.9
        return raw

    cases = [
        ("unknown contract version", edited(contract_version="2025-01-01")),
        ("a field missing (zone_id)", edited(zone_id=None)),
        ("no signature", copy.deepcopy(plain)),
        ("a value changed in transit", tampered()),
        ("the same reading twice", copy.deepcopy(good)),
        ("a number sent as text", sign({**copy.deepcopy(plain), "value": {"level_m": "high"}}, secret, "twin")),
    ]
    rows = []
    for what, raw in cases:
        perception = Perception([CONTRACT_VERSION], secret, True)
        if "twice" in what:
            perception.ingest(copy.deepcopy(raw))
        try:
            perception.ingest(raw)
            code, message = "accepted", ""
        except ContractError as error:
            code, message = error.code, error.message
        rows.append(f"<tr><td>{what}</td><td><code>{esc(code)}</code></td><td>{esc(message)}</td></tr>")
    return "".join(rows)


def page(n: int, part: str, body: str) -> str:
    return (f"<section class='page'><div class='top'><span><b>Triplet 03</b> · TSYP14 City Brain Convergence, Phase 1</span><span>{part}</span></div>{body}"
            f"<div class='foot'><span>City Brain team</span><span>{n}</span></div></section>")


def small_icon(name: str, tone: str) -> str:
    return f"<svg viewBox='0 0 48 48' aria-hidden='true'>{ICON(name, 24, 24, 34, tone, 3)}</svg>"


def rule(name: str, tone: str, text: str) -> str:
    return f"<div class='rule'>{small_icon(name, tone)}<p>{text}</p></div>"


LOGO_CSS = """
.lg{--panel:#fff;--fg:#111417;--muted:#3F464A;--line:#AEB5AF;--steel:#1B49CF;--ember:#A85F00;--wash:#F2F4F1;--body:Inter,Arial,sans-serif;--mono:'IBM Plex Mono',monospace}
.lg .card,.lg .card.new{fill:var(--panel);stroke:var(--line);stroke-width:1.4}.lg .card.partner{stroke-dasharray:6 4;stroke:var(--muted);fill:var(--wash)}
.lg .card.gate{stroke:var(--ember);stroke-width:2.6;fill:#FBF1E2}.lg .tile{fill:#fff;stroke:#D5DCE1;stroke-width:1}
.lg .glyph{fill:none;stroke:var(--steel);stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round}.lg .frame{fill:none;stroke:var(--line);stroke-width:1.2;stroke-dasharray:2 5}
.lg .arrow{fill:none;stroke:var(--steel);stroke-width:1.8}.lg .arrow.ember{stroke:var(--ember)}.lg .headfill{fill:var(--steel)}.lg .headember{fill:var(--ember)}
.lg .t{font:700 17px var(--body);fill:var(--fg)}.lg .s{font:400 14px var(--body);fill:var(--muted)}.lg .an{font:400 11px var(--mono);fill:var(--steel)}
.lg .k{font:400 11.5px var(--mono);fill:var(--muted);letter-spacing:.04em}
"""


def logo_fig(svg: str, height: int, size: str = "") -> str:
    """One of docs/diagrams/logo_architecture.py's drawings, cut to its content (the drawings are 1240 wide with room to spare below)."""
    import re
    svg = re.sub(r'viewBox="[^"]*" width="\d+" height="\d+"', f'viewBox="0 0 1240 {height}"', svg, count=1)
    return f"<div class='lg {size}'>{svg}</div>"


def part2(n: int) -> list[str]:
    """Part 2, five pages in the six subheadings the Phase 1 book asks of every layer. n is the first page number."""
    p = []
    p.append(page(n, "Part 2 · The City Brain", f"""
<h1>2. The City Brain</h1>
<p class='meta'>Written by the City Brain team · repository folder <code>triplet-03/brain/</code> · contract <code>2026-09-17</code>, Guardian contract 1.0 · key question: &ldquo;What should we do?&rdquo;</p>
<h2>2.1 Role and goals</h2>
<p>The Brain reads the Twin&rsquo;s live sensor readings, detects incidents (crimes, fires, accidents, jams, floods, grid overloads), asks the Guardian whether each reading can be trusted, chooses a response and carries it out through the Twin&rsquo;s actuators. It acts only on readings the Guardian has marked trusted, and only through the safety gate, the one component allowed to call an actuator.</p>
<div style='width:80%;margin:0 auto'>{fig_architecture()}</div>
<p class='cap'><b>Figure 2.1.</b> The Brain&rsquo;s components. Readings enter through the adapters at the top and actions leave only through the gate. With the Guardian team&rsquo;s contract 1.0 (dashed line) the Twin also feeds the Guardian, and valve, grid, signal and dispatch calls reach the Twin through the Guardian&rsquo;s audit. Amber dashes: a solver&rsquo;s answer enters a team&rsquo;s brief; green dashes: learning.</p>
<h3>Goals, and how each is shown</h3>
<table class='goals'><tr><th style='width:21%'>Goal</th><th style='width:42%'>How the Brain meets it</th><th>Shown by</th></tr>
<tr><td>Act only on trusted data</td><td>every call carries a <code>trust_ref</code> to a trusted, unexpired verdict</td><td>T13: a fake flood, nothing sent (Listing 2.1)</td></tr>
<tr><td>One way out</td><td>rules, agents and solvers propose; only the gate sends</td><td><code>brain redteam</code>: 24 of 24 attacks refused</td></tr>
<tr><td>Fast first, then thorough</td><td>a reflex acts at once; the team&rsquo;s plan follows, checked by code</td><td>T14: reflex in 15 ms, team plan 123 ms later</td></tr>
<tr><td>Safe when a part fails</td><td>no verdict, no action; a scripted team replaces a lost model</td><td>T15: Guardian silent, nothing more sent</td></tr>
<tr><td>Every step explained</td><td>each decision, hold or refusal is a named event with its reason</td><td>chained log per run; the &ldquo;why&rdquo; API</td></tr></table>
<p>All five Brain scenarios (T12 to T16) pass, with their logs in <code>logs/</code>; 1,114 tests; 60 of 60 held-out variants decide as their base scenario.</p>

"""))
    p.append(page(n + 1, "Part 2 · The City Brain", f"""
<h2>2.2 Architecture</h2>
<p>Figure 2.2 follows one reading through the components of Figure 2.1, in eighteen steps from the Twin to an action and its explanation. Each card names the component, the technology that runs it and, in blue, the brain function that inspired it. The analogy guides the design; the Brain does not model a brain.</p>
{logo_fig(incident_flow(), 596)}
<p class='cap'><b>Figure 2.2.</b> From a reading to a decision. Amber arrows lead to the gate: reflex proposals reach it at once, and the team&rsquo;s plan follows through the same gate. A plan the team makes the same way twice returns as a reflex after the sleep phase.</p>
<div class='cols'><div>
<h3>2.2.1 Incident detection</h3>
<p><b>Perception</b> checks the contract version, the HMAC signature, the sequence number and the value ranges, and refuses a bad reading with a code. <b>The Guardian&rsquo;s verdict</b>, requested with a 2 s deadline, decides whether the reading may count. <b>Forward models</b> learn each sensor&rsquo;s normal range from trusted readings only. A reading far outside it is flagged as a surprise, and the reflex it would trigger waits for a second source; a Kalman tracker forecasts when a river will reach the flood line. <b>Triage</b> runs the departments&rsquo; detectors to open or join an incident, and the <b>workspace</b> gives two incidents at a time the team&rsquo;s attention, ranked by severity, trust, surprise and urgency.</p>
<p>When an alarm matches no department, an incident has no procedure, or an incident stalls, the Brain emits <code>brain.human.needed</code> and asks a person.</p>
</div><div>
<h3>2.2.2 Decision method</h3>
<p><b>Rules</b> (13, in six packs) answer in milliseconds with no model. <b>Agent teams</b> weigh the case: for Police an Analyst, a Tactician and a Chief on LangGraph, using Groq models with <code>--llm</code> and a scripted stand-in otherwise or when the model fails; the other departments use a two-role desk. <b>Solvers</b> compute what should not be guessed: OR-Tools min-cost flow for dispatch, CP-SAT for a perimeter and for load shedding, Dijkstra for a green corridor and the Kalman forecast for floods. They run before the agents and their answers go into the agents&rsquo; brief, so a model that never calls a tool still reads them.</p>
<p>Code then verifies the agents&rsquo; plan (<code>verify_case</code>, <code>verify_plan</code>, <code>verify_desk</code>) before it reaches the gate.</p>
</div></div>
<h4>Departments</h4>
<table><tr><th style='width:16%'>Department</th><th style='width:14%'>Incidents</th><th>Acts through</th><th style='width:21%'>Reasoning</th></tr>
<tr><td>Police</td><td>crime</td><td><code>dispatch_unit</code> (pursuit, contain), <code>broadcast_alert</code>, <code>recall_unit</code></td><td>Analyst, Tactician, Chief</td></tr>
<tr><td>Fire, Ambulance</td><td>fire, accident</td><td><code>dispatch_unit</code>, <code>broadcast_alert</code></td><td>desk: Analyst, Chief</td></tr>
<tr><td>Traffic control</td><td>jam</td><td><code>set_signal_phase</code> (hold green, also for an ambulance&rsquo;s route)</td><td>desk</td></tr>
<tr><td>Disaster response</td><td>flood</td><td><code>broadcast_alert</code>, <code>set_valve_state</code> (a person approves)</td><td>desk</td></tr>
<tr><td>Utilities</td><td>overload, smog</td><td><code>broadcast_alert</code>, <code>set_grid_connection</code> (a person approves)</td><td>desk</td></tr></table>
<p>A department is three files (detectors and actuators, reflex rules, a playbook): a new kind of incident is a new pack.</p>
"""))
    p.append(page(n + 2, "Part 2 · The City Brain", f"""
<h3 style='margin-top:0'>2.2.3 Choosing an actuator</h3>
<p>The Brain picks an actuator in three steps. The incident type decides which department may act and with which actuator; a solver, or the nearest free station, picks the device; and the gate decides whether the call goes out. No other code path calls the Twin.</p>
{logo_fig(planner(), 566)}
<p class='cap'><b>Figure 2.3.</b> The planning graph for one incident (LangGraph). The solver and the agent team work in parallel, the better plan is kept, a valve or grid call pauses for a person, and each step is checkpointed to SQLite so a run can resume and be replayed.</p>
<div class='cols'><div>
<h4>Station or device</h4>
<p>The nearest free station by hop distance, never a quarantined or reserved one. In T16 the Guardian quarantines a station, the gate refuses calls to it with reason <code>quarantine</code>, and another station is sent. When two incidents need the same kind of unit, the dispatch solver plans both together, and its choice is used only if it costs less: for two collisions it may send the far ambulance to the first so that the near one stays free for the second. On 100 random cities its plans cost 17% less than nearest-first (20.39 against 24.63) and match brute force (<code>brain optimise-bench</code>).</p>
</div><div>
<h4>Grid cut or signal</h4>
<p>A cascade analysis weighs what each grid cut would black out, with a hospital weighted 10, and the shed solver picks the cheapest set of cuts that removes the excess load. A corridor holds the signals on an ambulance&rsquo;s route at green. A dispatched unit&rsquo;s <code>unit_status</code> readings close the incident, and an arrest recalls every unit still out.</p>
</div></div>
<p class='cap' style='margin:4mm 0 0'><b>Table 2.1.</b> The safety gate&rsquo;s eleven checks, in the order they run on every proposal. The first that fails stops the call and its reason goes to the timeline; quoted reasons are from the canonical logs. A call that passes is signed (HMAC, key id, one-time nonce) and sent; an approved valve or grid call runs every check again.</p>
{gate_table()}

"""))
    p.append(page(n + 3, "Part 2 · The City Brain", f"""
<h2>2.3 Tech stack and why</h2>
<p>Everything runs offline on one laptop: the embedding model is in the Docker image, the screen loads nothing from the internet, and the scripted team answers when no model is reachable.</p>
<p class='cap' style='margin:2mm 0 0'><b>Table 2.2.</b> The stack by job. Each logo belongs to its owner.</p>
{stack_table()}
<h2>2.4 Interfaces in/out</h2>
<table><tr><th style='width:16%'>Direction</th><th style='width:30%'>Message</th><th>Transport and contract</th></tr>
<tr><td>In, from the Twin</td><td>signed sensor readings; the city layout</td><td>MCP <code>list_readings(cursor)</code> every 200 ms and <code>get_topology()</code>; plain HTTP or MQTT as alternatives</td></tr>
<tr><td>In, from the Guardian</td><td>a signed verdict per reading; containment</td><td>contract 1.0: <code>POST /v1/verdicts/request</code> by sensor and sequence number, HMAC checked; <code>GET /v1/containment</code></td></tr>
<tr><td>Out, to the Twin</td><td>signed calls for the six actions (<code>dispatch_unit</code>, <code>set_valve_state</code>&hellip;)</td><td>valve, grid, signal, dispatch via the Guardian&rsquo;s audited <code>/v1/actuator-calls</code>; broadcast and recall to the Twin directly</td></tr>
<tr><td>Out, to the screen and partners</td><td>timeline events; the reasons for a decision; read-only tools</td><td>SSE <code>GET /events</code> (CloudEvents 1.0, 55 types in AsyncAPI); <code>/api/decisions/{{id}}/explanation</code>; MCP at <code>/mcp</code></td></tr></table>
<div style='width:86%;margin:0 auto'>{fig_interop()}</div>
<p class='cap'><b>Figure 2.4.</b> Where the logic ends and partners begin. Phase 2 reshuffles the triplets, so a new Twin or Guardian must be a new adapter class or an edit of <code>config/partners.yaml</code>, never a change to the decision logic, which reaches partners only through the two ports.</p>
<table><tr><th style='width:26%'>The jury looks for</th><th>Where the Brain does it, and the check that keeps it true</th></tr>
<tr><td>Logic separate from partner I/O</td><td>two ports in <code>ports.py</code>, one adapter class per protocol; <code>tests/test_layering.py</code> enforces it</td></tr>
<tr><td>A complete Interface Card</td><td><code>INTERFACE.md</code>, an example of every message; <code>tests/test_contracts.py</code> validates each</td></tr>
<tr><td>Settings in configuration</td><td><code>config/partners.yaml</code>, secrets from the environment; <code>brain onboard</code> maps a renamed Twin</td></tr>
<tr><td>Runs alone with mocks (R1)</td><td><code>mocks/twin</code>, <code>mocks/guardian</code>; <code>brain conformance</code> runs 19 checks on a real partner</td></tr></table>
"""))
    p.append(page(n + 4, "Part 2 · The City Brain", f"""
<h2>2.5 Security measures</h2>
<p>The Brain treats every input as untrusted until it passes its checks, and every model answer as a proposal that code must verify. Valve and grid calls also need a person&rsquo;s signed approval. Threats are mapped to MITRE ATT&amp;CK for ICS and, for the AI components, to MITRE ATLAS (<code>docs/SECURITY-MITRE.md</code>).</p>
<p class='cap' style='margin:2mm 0 0'><b>Listing 2.1.</b> T13, a fake flood, from <code>logs/t13-20261108T153847Z.jsonl</code> (abridged). The gauge reads 1.80 m, the Guardian says untrusted, and the gate refuses both the warning and the valve.</p>
<pre class='log'>15:38:51.522  brain.reading.received  wl-01-02  level 1.80 m
15:38:51.526  brain.verdict.received  verdict-000004  untrusted
15:38:51.526  brain.incident.opened   flood, zone-01, evidence untrusted
15:38:51.547  brain.action.blocked    broadcast_alert  trust_ref: no Guardian verdict referenced
15:38:51.548  brain.action.blocked    set_valve_state valve-01-01  trust_ref: no Guardian verdict referenced
15:38:51.975  brain.incident.closed   cleared: wl-01-01 still reads 0.30 m</pre>
<table><tr><th style='width:20%'>Boundary</th><th>Control</th></tr>
<tr><td>Twin to Brain: readings</td><td>HMAC-SHA256 or Ed25519 over canonical JSON, key ids with expiry, a rising sequence number per sensor, schema and ranges; only allowlisted fields are kept, so demographic fields never reach a decision</td></tr>
<tr><td>Guardian to Brain: verdicts</td><td>schema check and the verdict&rsquo;s HMAC (contract 1.0); more independent trusted sources as impact rises</td></tr>
<tr><td>People and partners to the API</td><td>scoped bearer tokens off loopback (read, push, approve, admin), body and rate limits; a partner may push only <code>twin.*</code> or <code>guardian.*</code> events, and a forged <code>brain.*</code> event is refused</td></tr>
<tr><td>Brain to the language model</td><td>ids limited to safe characters before any prompt; read-only tools, with no actuating tool; models choose zone ids, not free text; code verifies the plan, then the gate checks it</td></tr>
<tr><td>Brain to Twin: calls</td><td>eleven gate checks; each call signed with its time and a one-time nonce; a valve or grid call needs a signed approval bound to its exact parameters and used once</td></tr>
<tr><td>Brain to its own disk</td><td>hash-chained log with a signed head; learning from trusted readings only; self-tuning limited to a listed set of parameters, each with a range</td></tr></table>
<table><tr><th style='width:26%'>MITRE technique</th><th style='width:46%'>Attack run against the code</th><th>Result</th></tr>
<tr><td>ICS T1692.002, forged reading</td><td>wrong key, no signature, a field edited after signing, a replayed sequence number, <code>alg: none</code></td><td>refused every time</td></tr>
<tr><td>ICS T1692.001, T0849, forged call</td><td>an approval reused with changed parameters; the Twin pushing as the Guardian</td><td>refused</td></tr>
<tr><td>Enterprise T1190, T1078</td><td>no token, a forged token, a read token doing admin work, 28 path spellings with 7 methods</td><td>none got through</td></tr>
<tr><td>ATLAS AML.T0051, T0053</td><td>30 prompt-injection strings in sensor ids and values; a tool that tries to actuate</td><td>dropped before any prompt; no such tool exists</td></tr></table>
<p><code>brain redteam</code> runs 24 attacks; all were refused when re-run for this report. When the Guardian stops answering, the Brain acts on nothing it has not judged (T15), which is the Guardian&rsquo;s own fail-safe rule.</p>
<p><b>Reproduce:</b> <code>uv run brain scenario t13 --inproc --speed 0</code>, <code>uv run brain redteam</code>, <code>uv run brain verify-log --scenarios</code>.</p>
<h2>2.6 Known limitations</h2>
<div class='cols'><div><ul class='items'>
<li><b>No joint run with the real Twin yet.</b> Against the live Guardian we ran the fake and real flood and T16. Next: run T12 to T16 against the Twin team&rsquo;s Twin.</li>
<li><b>The mock Guardian is scripted.</b> T13 and T16 show what the Brain does with a given verdict, not whether a real Guardian would issue it. Next: rerun both with <code>docker-compose.guardian.yml</code>.</li>
<li><b>Tuned on stand-ins.</b> Which sensors move together, and whether sensors in one zone are independent, waits for the real Twin&rsquo;s data. Next: record a normal day from it (<code>docs/TWIN-HANDOVER.md</code>).</li>
</ul></div><div><ul class='items'>
<li><b>TLS and the freshness limit are off by default.</b> Signatures still protect readings and calls. Next: set <code>guardian.tls</code> and <code>twin.max_age_s</code> on the live stack.</li>
<li><b>Guardian alerts are not read.</b> An actuator the Guardian flags as unreliable appears in its containment list, which the gate obeys; a <code>compromised_twin</code> alert does not reach the Brain. Next: read <code>WS /v1/ws/verdicts</code> in the adapter.</li>
</ul></div></div>
"""))
    return p


def pages() -> list[str]:
    p = []
    p.append(page(1, "Part 0 · Triplet overview and integration", f"""
<h1>The City Brain inside the triplet</h1>
<p class='lede'>Three layers, one loop. The <b>Twin</b> is the simulated city, the <b>Guardian</b> says which readings can be believed, and the <b>City Brain</b> decides and acts. Figure 1 is the Brain's part of the global diagram: every box is a component that exists and runs, and the arrows are the ways they hand work to each other.</p>
<div style='width:82%;margin:0 auto'>{fig_architecture()}</div>
<p class='cap'>Figure 1. Global architecture. Readings enter at the top and actions leave only through the gate. The dotted line across the top is the Guardian team&rsquo;s design, where the Twin also feeds the Guardian. Dashed amber arrows show where a solver's answer enters a team's brief; dashed green arrows show the learning loop.</p>
<table><tr><th>Link</th><th>How it talks</th><th>What keeps it safe</th></tr>
<tr><td>Twin to Brain</td><td>MCP tool <code>list_readings</code> (also HTTP and MQTT); city layout from <code>get_topology</code></td><td>contract version, HMAC signature, sequence number, ranges</td></tr>
<tr><td>Brain to Guardian</td><td>REST, 2 s deadline. Our contract: <code>POST /verdicts</code> with the reading, <code>GET /quarantine/{{id}}</code>. The Guardian team&rsquo;s 1.0: <code>POST /v1/verdicts/request</code> by sensor and sequence number, <code>GET /v1/containment</code></td><td>a silent Guardian means no verdict, so no action on readings it has not judged</td></tr>
<tr><td>Twin to Guardian</td><td>the Guardian team&rsquo;s contract only: the Twin pushes <code>POST /v1/readings</code> (or the Guardian pulls). The Brain is not on this path</td><td>HMAC on every reading; the Guardian checks sequence and timestamp</td></tr>
<tr><td>Brain to Twin</td><td>signed actuator calls through the Twin's MCP tools; with the Guardian team&rsquo;s Guardian, valve, grid, signal and dispatch calls go through its <code>POST /v1/actuator-calls</code>, which audits them before forwarding; results come back as readings and <code>unit_status</code></td><td>the gate: 11 checks, trust reference, idempotency, human approval</td></tr>
<tr><td>Any partner to the screen</td><td>CloudEvents over SSE; a partner may push <code>twin.*</code> or <code>guardian.*</code> events</td><td><code>brain.*</code> pushes are refused; scoped tokens off loopback</td></tr></table>
"""))
    p.append(page(2, "Part 0 · One scenario traced end to end", f"""
<h1>One scenario, end to end: crime and pursuit</h1>
<p class='lede'>A robbery is caught on camera in Downtown (scenario <code>t14</code>). The trace below is the run committed in <code>logs/t14-20261108T153858Z.jsonl</code>, at normal speed; times are measured from the robbery report. Read it left to right: the same event is touched by every layer and by most components of the Brain, and each hand-off is an event on the timeline.</p>
{fig_trace()}
<p class='cap'>Figure 2. The reflex dispatches 15 ms after the reading that completes the evidence (10 ms after its verdict); the team&rsquo;s fuller plan follows about 120 ms later and passes the same gate. The perimeter solver checks the team's plan (2 units hold, 2 are used). Recorded against our stand-in Guardian, to which the Brain sends the reading itself. With the Guardian team&rsquo;s contract 1.0 the Brain asks by sensor and sequence number and the dispatches pass through the Guardian&rsquo;s audit.</p>
<div class='cols'><div>
<h3>What this shows</h3>
<p><b>Trust first.</b> The camera reading is acted on only after the Guardian's verdict; the second reading (a citizen running away at 18 km/h) lifts the suspect's score to 0.82.</p>
<p><b>Two speeds.</b> A rule dispatches the first unit at once; the Analyst, Tactician and Chief then place a perimeter, and code verifies it before anything is proposed.</p></div><div>
<h3>What it would look like if it went wrong</h3>
<p><b>A fake flood (t13):</b> the Guardian marks the reading untrusted and the gate refuses the warning and the valve call. <b>A layer down (t15):</b> the Guardian stops answering; the Brain says so once and acts on no reading the Guardian has not judged (every call still needs a trusted verdict).</p></div></div>
"""))
    p.append(page(3, "Part 0 · Shared decisions", f"""
<h1>How the layers were made to fit</h1>
<p class='lede'>The Brain is built so that a partner can be replaced without touching the Brain: everything that depends on the Twin's naming, units or speed is configuration, not code, and every behaviour is agreed with the partners in the Interface Card.</p>
<div class='cols'><div>
{rule('plug', BLUE, '<b>One contract.</b> The Data Dictionary messages, one example of each in <code>contracts/examples/</code>, JSON Schemas exported by one command, a four-edit rule for any change.')}
{rule('shield', GOOD, '<b>Trust is shared.</b> The Guardian judges; the Brain scales trust by the verdict&rsquo;s confidence and never learns from an untrusted reading.')}
{rule('lock', BLUE, '<b>One way out.</b> Only the gate signs a call; agents get read-only tools; a valve or the grid needs a person.')}
{rule('code', MUTED, '<b>Every layer runs alone.</b> The mocks of the Twin and the Guardian ship with the Brain; <code>brain conformance</code> checks a real partner against the same contract.')}
</div><div>
{rule('route', WARN, '<b>Partners differ.</b> <code>brain onboard</code> proposes renames and units for a Twin that names things differently and never edits config.')}
{rule('alert', BAD, '<b>Failure is a state.</b> A silent Guardian, a missing Twin, a spent model quota and an unknown alarm each have a named event and a defined behaviour.')}
{rule('chart', INK, '<b>Evidence, not claims.</b> 1,114 tests, 5 Test Book scenarios, 60 held-out variants, a hash-chained log per run, and <code>brain rehearse</code> as the freeze check.')}
{rule('box', GOOD, '<b>One command.</b> <code>make full</code> builds one image and starts the Brain, both stand-ins, Neo4j and Qdrant.')}
</div></div>
<h2>The messages that cross the layers</h2>
<table><tr><th>Message</th><th>From, to</th><th>Examples in the repository</th></tr>
<tr><td>Sensor reading envelope</td><td>Twin to Brain</td><td><code>reading.water_level.json</code>, <code>reading.cctv_anomaly.json</code>, and five more</td></tr>
<tr><td>Trust verdict</td><td>Guardian to Brain</td><td><code>verdict.json</code> (status, confidence, expiry)</td></tr>
<tr><td>Actuator call and result</td><td>Brain to Twin and back</td><td><code>actuator_call.*.json</code> (six actions), <code>actuator_result.*.json</code></td></tr>
<tr><td>Approval</td><td>person to Brain</td><td><code>approval.json</code> (signed, bound to the call, single use)</td></tr>
<tr><td>Timeline event</td><td>Brain to screen and partners</td><td><code>timeline_event.json</code>; 55 event types in <code>docs/asyncapi.yaml</code></td></tr></table>
<h2>When something fails, the layers stay joined</h2>
{fig_failures()}
<p class='cap'>Figure 2b. Each failure has a name, a defined behaviour and a scenario or command that shows it.</p>
<h2>Where the Brain still depends on the other teams</h2>
<p>The Brain has run end to end only against stand-ins for the Twin and the Guardian. Which sensors move together and whether same-type sensors in one zone are independent are still to be measured on the real Twin (<code>docs/TWIN-HANDOVER.md</code>); each is a switch that is built and waits for the answer.</p>
"""))
    p.append(page(4, "Part 0 · Interoperability", f"""
<h1>Built to connect to a team it has never met</h1>
<p class='lede'>In Phase 2 the triplets are reshuffled. A new Twin or Guardian means a new adapter or a changed configuration file, never a change to the decision logic.</p>
{fig_interop()}
<p class='cap'>Figure 2c. Everything outside the two ports can be replaced; the logic cannot tell which partner it talks to.</p>
<h2>The five things the jury looks for, and where to check each</h2>
<table style='font-size:7.3pt'><tr><th style='width:21%'>Requirement</th><th>What the repository does</th><th style='width:27%'>How to check it</th></tr>
<tr><td><b>Logic separate from partner I/O</b></td><td>The logic reaches partners only through <code>TwinPort</code> and <code>GuardianPort</code> (<code>ports.py</code>). Protocols live in <code>adapters/</code>, one class each: MCP, HTTP and MQTT for the Twin, REST for the Guardian.</td><td><code>tests/test_layering.py</code> fails if logic imports an adapter or the reverse; <code>tests/test_twin_mqtt.py</code> runs <code>t14</code> over MQTT.</td></tr>
<tr><td><b>A complete Interface Card</b></td><td><code>INTERFACE.md</code>: what the Brain receives and sends, an example of each message, how to repoint it, how it authenticates. Long form: <code>docs/INTEGRATION-brain.md</code>.</td><td><code>tests/test_contracts.py</code> validates every example in <code>contracts/examples/</code> and verifies each signature.</td></tr>
<tr><td><b>Settings in configuration</b></td><td><code>config/partners.yaml</code> holds each partner's adapter, address, secret variable name, renames and units. Secrets come from the environment; code defaults are loopback addresses.</td><td>A test requires the YAML to equal the defaults; <code>brain onboard</code> proposes edits for a renamed Twin.</td></tr>
<tr><td><b>Standard protocols and formats</b></td><td>MCP, REST and MQTT; JSON Schema; HMAC-SHA256 or Ed25519 over canonical JSON; Server-Sent Events and CloudEvents 1.0 described by AsyncAPI; TLS; OpenTelemetry.</td><td><code>contracts/schemas/</code>; <code>docs/asyncapi.yaml</code> (55 event types).</td></tr>
<tr><td><b>Validation and clear errors</b></td><td>Every reading is checked on entry; a refusal carries a code and a reason (below) and goes to the timeline. A bad or missing verdict means no action; a failing Twin tool is named in the error.</td><td><code>brain conformance</code> checks a real partner; <code>brain redteam</code>: 24 attacks, all refused.</td></tr></table>
<h2>What a partner is told when it sends something unexpected</h2>
<table style='font-size:7.3pt'><tr><th style='width:21%'>The partner sends</th><th style='width:22%'>Code</th><th>The Brain's answer, as the code returns it</th></tr>
{rejection_rows()}</table>
<p class='cap'>Table 2. Run through the Brain's own perception code when this report is built. Not shown yet: the Brain has run only against mocks of the Twin and the Guardian; the HTTP and MQTT adapters are agreed but not yet run against a partner.</p>
"""))
    p += part2(5)
    p.append(page(10, "Part 4 · Test Book (the Brain&rsquo;s scenarios)", f"""
<h1>4. Test Book (the Brain&rsquo;s scenarios)</h1>
<p>Five scenarios, each one trigger (<code>scenarios/triggers/tN.sh</code> or <code>uv run brain scenario tN</code>) and one hash-chained log in <code>logs/</code>, with the expected outputs in the scenario file. Together they cover the brief&rsquo;s four interaction rows; the Guardian team&rsquo;s T1 to T11 are in the shared <code>TESTBOOK.md</code>. The generated list, in the book&rsquo;s fields, is <code>brain/docs/TESTBOOK-brain.md</code>.</p>
<table><tr><th>ID</th><th>Scenario</th><th>Interaction</th><th>Expected output</th></tr>
<tr><td>T12</td><td>A calm day</td><td>Twin &rarr; Brain</td><td>no incident, no actuator call: the Brain does not overreact</td></tr>
<tr><td>T13</td><td>A fake flood</td><td>Twin &rarr; Guardian, Brain &rarr; Guardian</td><td>the gauge is untrusted; the gate refuses the warning and the valve call; nothing reaches the city</td></tr>
<tr><td>T14</td><td>A crime and a pursuit</td><td>Twin &rarr; Brain, Brain &rarr; Guardian</td><td>reflex dispatch, a team perimeter checked and verified, units recalled at the arrest</td></tr>
<tr><td>T15</td><td>A flood, an attack and a layer down</td><td>all three</td><td>warning sent, valve held, forged report sends no police; once the Guardian is silent, one &lsquo;Guardian away&rsquo; and no action on unjudged readings</td></tr>
<tr><td>T16</td><td>A quarantined police station</td><td>Brain &rarr; Guardian</td><td>the gate refuses calls to the quarantined station with reason <code>quarantine</code>; a different station is used</td></tr></table>
"""))
    return p


def document(embed_fonts: bool, body: list[str] | None = None, title: str = "City Brain: report, Parts 0, 2 and 4") -> str:
    import re
    faces = ""
    for family, weight, style, file in (("Source Serif 4", 400, "normal", "source-serif-4-latin-400-normal"), ("Source Serif 4", 400, "italic", "source-serif-4-latin-400-italic"),
                                        ("Source Serif 4", 600, "normal", "source-serif-4-latin-600-normal"), ("Inter", 400, "normal", "inter-latin-400-normal"),
                                        ("Inter", 600, "normal", "inter-latin-600-normal"), ("Inter", 700, "normal", "inter-latin-700-normal"),
                                        ("IBM Plex Mono", 400, "normal", "ibm-plex-mono-latin-400-normal")):
        path = FONTS / f"{file}.woff2"
        src = "data:font/woff2;base64," + base64.b64encode(path.read_bytes()).decode() if embed_fonts else path.as_uri()
        faces += f"@font-face{{font-family:'{family}';font-weight:{weight};font-style:{style};src:url('{src}') format('woff2')}}"
    html_body = "".join(pages() if body is None else body)
    return re.sub(r"\s+\n", "\n", f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{title}</title><style>{faces}{CSS}{LOGO_CSS}</style></head><body>{html_body}</body></html>")


def main() -> int:
    browser = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if browser is None:
        print("error: needs Chromium to print the PDF", file=sys.stderr)
        return 1
    PAGE.write_text(document(True), encoding="utf-8")
    with tempfile.TemporaryDirectory() as work:
        for out, html_text in ((PDF, document(False)), (PART2, document(False, part2(1), "City Brain: report, Part 2"))):
            src = Path(work) / "report.html"
            src.write_text(html_text, encoding="utf-8")
            subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--allow-file-access-from-files",
                            f"--user-data-dir={work}/profile", f"--print-to-pdf={out}", src.as_uri()], check=True, capture_output=True, timeout=180)
    print(f"wrote {PDF.relative_to(ROOT)}, {PART2.relative_to(ROOT)} and {PAGE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
