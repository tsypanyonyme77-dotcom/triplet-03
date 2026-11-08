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
from logo_architecture import GLYPHS, big_picture, defence, incident_flow, logo_uri, planner  # noqa: E402

FONTS = ROOT / "src/brain/api/static/fonts"
PDF, PAGE = HERE / "report-city-brain.pdf", HERE / "report-city-brain.html"
PART2 = HERE / "report-part2-city-brain.pdf"  # Part 2 alone, five pages, for the triplet's merged report

INK, INK2, MUTED, RULE, BOARD, STRIP = "#111417", "#3F464A", "#636B6F", "#AEB5AF", "#E6E9E4", "#FFFFFF"
BLUE, GOOD, WARN, BAD = "#1B49CF", "#18794A", "#A85F00", "#C0311E"
WASH = {BLUE: "#EEF2FC", GOOD: "#EAF4EE", WARN: "#FBF1E2", BAD: "#FBECE9", INK: "#F2F4F1", MUTED: "#F2F4F1"}
SANS, MONO = "B612, sans-serif", "'B612 Mono', monospace"


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
    b.append(LINES(705, 246, ["a verdict on", "every reading", "", "a quarantine list", "of actuators", "", "v1 only: audits", "valve, grid, signal", "and dispatch calls"], 10, 14, INK2, "middle"))
    # Brain frame
    b.append(R(190, 14, 420, 656, BOARD, INK, 2, 12))
    b.append(T(204, 34, "City Brain layer", 13, 700) + T(594, 34, "every arrow is an event on the timeline", 9, 400, MUTED, "end"))
    X1, X2, X3, W3, WF = 204, 332, 460, 126, 382
    y1, y2, y3, y4, yg, y6 = 46, 124, 232, 320, 436, 512
    b.append(NODE(X1, y1, WF, 62, "Ports and adapters", ["MCP, HTTP or MQTT in; REST (or v1) to the Guardian"], "plug", BLUE, ("modelcontextprotocol", "mqtt")))
    b.append(NODE(X1, y2, 120, 92, "Knowledge", ["39 procedures", "hybrid search"], "book", MUTED, ("qdrant",)))
    b.append(NODE(X2, y2, 120, 92, "City graph", ["zones, units,", "incidents"], "db", MUTED, ("neo4j", "networkx")))
    b.append(NODE(X3, y2, W3, 92, "Perception", ["signature, replay,", "demographics dropped"], "shield", GOOD))
    b.append(NODE(X1, y3, 120, 70, "Workspace", ["salience, 2 seats,", "packs bid"], "eye", INK))
    b.append(NODE(X2, y3, 120, 70, "Triage", ["detectors open", "an incident"], "route", INK))
    b.append(NODE(X3, y3, W3, 70, "Forward models", ["prediction error,", "level forecast"], "dial", GOOD))
    b.append(NODE(X1, y4, 120, 100, "Reflex rules", ["milliseconds,", "no model"], "bolt", INK))
    b.append(NODE(X2, y4, 120, 100, "Teams", ["Police: 3 agents", "5 desks of two"], "agents", INK, ("langgraph", "groq")))
    b.append(NODE(X3, y4, W3, 100, "Solvers", ["dispatch, perimeter,", "shed, forecast,", "corridor"], "scale", WARN, ("ortools",)))
    b.append(NODE(X1, yg, WF, 62, "Safety gate: the only way out", ["11 checks, a person approves a valve or the grid"], "lock", BLUE, accent=True))
    b.append(NODE(X1, y6, 120, 82, "Memory", ["episodes, learned", "reflexes, Academy"], "loop", GOOD))
    b.append(NODE(X2, y6, 120, 82, "Evidence", ["sealed log, why,", "counterfactuals"], "chain", MUTED, ("cloudevents",)))
    b.append(NODE(X3, y6, W3, 82, "Screen and API", ["Strip Board, canopy,", "approvals, alerts"], "monitor", MUTED, ("fastapi",)))
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
    b.append(ARROW([(0, ly), (30, ly)], BLUE, width=2) + T(36, ly + 4, "signed calls", 9.5, 400, INK2))
    b.append(ARROW([(120, ly), (150, ly)], WARN, dash="4 3") + T(156, ly + 4, "solver answers go into the team's brief", 9.5, 400, INK2))
    b.append(ARROW([(380, ly), (410, ly)], GOOD, dash="4 3") + T(416, ly + 4, "learning and trust", 9.5, 400, INK2))
    b.append(ARROW([(540, ly), (570, ly)], INK) + T(576, ly + 4, "data", 9.5, 400, INK2))
    # v1 only: the Guardian team's Guardian is also fed by the Twin. The arrow runs above the Brain, so the figure is shifted down to make room.
    link = ARROW([(75, 60), (75, 20), (705, 20), (705, 160)], INK, "v1 only: the Twin also pushes every reading to the Guardian (POST /v1/readings); the Guardian forwards none to the Brain", 390, 13, dash="4 3", size=8.6)
    return SVG(780, 730, f"<g transform='translate(0,30)'>{''.join(b)}</g>" + link, "Global architecture: Twin, City Brain and Guardian")



# --------------------------------------------------------------------------------------------------- figure: the line between logic and partners


def fig_interop() -> str:
    b = []
    b.append(R(0, 10, 100, 152, STRIP, INK, 1.4, 9, "5 3") + BADGE("city", 50, 40, 34, MUTED) + T(50, 76, "Twin", 12.5, 700, INK, "middle") + LINES(50, 94, ["any engine that", "speaks the card"], 9, 12, MUTED, "middle"))
    b.append(R(680, 10, 100, 152, STRIP, INK, 1.4, 9, "5 3") + BADGE("shield", 730, 40, 34, GOOD) + T(730, 76, "Guardian", 12.5, 700, INK, "middle") + LINES(730, 94, ["any service that", "issues a verdict"], 9, 12, MUTED, "middle"))
    b.append(NODE(130, 10, 138, 152, "Twin adapters", ["one class each:", "MCP (default),", "HTTP, MQTT", "", "protocol, TLS and", "retries stay here"], "plug", BLUE, ("modelcontextprotocol", "mqtt")))
    b.append(NODE(512, 10, 138, 152, "Guardian adapter", ["REST (ours) or v1", "(theirs), a class each", "", "a bad or late", "verdict becomes", "degraded mode,", "never a crash"], "plug", BLUE))
    b.append(R(286, 10, 208, 152, BOARD, INK, 2, 12) + T(298, 32, "Decision logic", 12, 700) + LINES(298, 48, ["perception, triage, workspace,", "teams, solvers, safety gate"], 9.3, 12, INK2))
    b.append(NODE(298, 78, 184, 76, "Checks on entry", ["schema, contract version,", "signature, replay, id pattern;", "a refusal has a code and a reason"], "shield", GOOD, accent=True))
    for x, name in ((268, "TwinPort"), (494, "GuardianPort")):
        b.append(R(x, 10, 18, 152, WASH[BLUE], BLUE, 1.6, 4) + T(x + 9, 86, name, 9.3, 700, BLUE, "middle", MONO, rotate=-90))
    b.append(ARROW([(100, 58), (130, 58)], INK, both=True) + ARROW([(650, 58), (680, 58)], INK, both=True))
    b.append(ARROW([(100, 118), (130, 118)], BLUE, width=1.8, both=True) + ARROW([(650, 118), (680, 118)], GOOD, both=True))
    b.append(NODE(130, 192, 220, 78, "config/partners.yaml", ["address, adapter, secret names,", "renames and units per partner", "no partner address in the logic"], "file", WARN, accent=True))
    b.append(ARROW([(200, 192), (200, 162)], WARN, dash="4 3", width=1.6) + ARROW([(330, 192), (330, 176), (581, 176), (581, 162)], WARN, dash="4 3", width=1.6))
    b.append(NODE(366, 192, 280, 78, "The Interface Card and the contract", ["INTERFACE.md, JSON Schemas, an example of every", "message; JSON, HMAC-SHA256 or Ed25519;", "CloudEvents 1.0 for the timeline"], "tag", BLUE))
    b.append(NODE(662, 192, 118, 78, "Conformance", ["brain conformance", "tests a real partner"], "check", GOOD))
    return SVG(780, 280, "".join(b), "The line between the Brain's logic and its partners")


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
        (0, 2, "cctv_anomaly robbery 0.9, signed", BLUE, "+0 ms", None, False),
        (2, 1, "judge this reading", GOOD, None, None, False),
        (1, 2, "trusted 0.97", GOOD, "+3 ms", None, False),
        (3, 3, ["inc-0001 crime", "zone-07, seat 1"], INK, "+4 ms", None, False),
        (0, 2, "citizen sighting: 18 km/h away", BLUE, "+218 ms", None, False),
        (3, 3, ["suspect cit-88213", "score 0.82"], INK, "+438 ms", None, False),
        (3, 4, "rule POL-001", INK, None, None, False),
        (4, 7, "dispatch_unit pursuit", BLUE, "+441 ms", None, False),
        (7, 1, "quarantined?", GOOD, None, "3 3", True),
        (7, 0, "signed call", BLUE, "+442 ms", None, False),
        (0, 7, "dispatched unit-p-01", INK, "+444 ms", None, False),
        (3, 5, "recruit the team", INK, None, None, False),
        (5, 5, ["Analyst: pursue", "Tactician: 4 opts"], INK, "+449 ms", None, False),
        (5, 6, "perimeter check", WARN, None, "4 3", False),
        (6, 5, "2 units would hold", WARN, "+509 ms", "4 3", False),
        (5, 5, ["Chief: perimeter", "verified by code"], INK, "+509 ms", None, False),
        (5, 7, "contain x2 and an alert", BLUE, "+511 ms", None, False),
        (7, 0, "3 signed calls, 3 results", BLUE, "+515 ms", None, False),
        (0, 2, "units report; suspect caught", BLUE, "+15.5 s", None, False),
        (3, 3, ["incident closed", "apprehended"], INK, None, None, False),
        (4, 7, "recall_unit x2", BLUE, "+15.5 s", None, False),
    ]
    for a, c, lab, tone, ms, dash, both in rows:
        b.append(step(y, a, c, lab, tone, ms, dash, both))
        y += 22.5
    return SVG(780, 548, "".join(b), "Crime and pursuit traced across the layers with measured times")


# --------------------------------------------------------------------------------------------------- figure 7 gate


def fig_gate() -> str:
    checks = [("file", "schema"), ("plug", "capability"), ("key", "allowlist"), ("clock", "incident open"), ("shield", "trust_ref"), ("scale", "evidence"),
              ("person", "human approval"), ("stamp", "idempotency"), ("clock", "cooling gap"), ("stop", "quarantine"), ("chart", "budget")]
    b = []
    for i, (ic, name) in enumerate(checks):
        row, col = divmod(i, 6)
        x, y = col * 130, row * 96
        tone = BLUE if name in ("trust_ref", "evidence", "human approval") else INK
        b.append(R(x, y, 120, 82, STRIP, tone, 1.2, 8) + BADGE(ic, x + 24, y + 28, 32, tone) + T(x + 46, y + 22, f"{i + 1}", 12, 700, MUTED) + T(x + 46, y + 38, "check", 8.6, 400, MUTED))
        b.append(T(x + 10, y + 68, name, 10, 700))
        if i not in (5, 10):
            b.append(ARROW([(x + 121, y + 41), (x + 129, y + 41)], INK))
    b.append(R(650, 96, 130, 82, WASH[GOOD], GOOD, 1.5, 8) + BADGE("check", 676, 124, 32, GOOD) + T(700, 120, "signed", 10, 700, GOOD) + T(700, 133, "and sent", 10, 700, GOOD) + LINES(660, 158, ["HMAC, nonce,", "key id"], 9, 11, INK2))
    b.append(ARROW([(640, 137), (649, 137)], GOOD))
    b.append(R(0, 204, 780, 44, WASH[BAD], BAD, 1.2, 8) + BADGE("stop", 26, 226, 28, BAD) + T(52, 222, "Any check that fails stops the call and records why:", 10.5, 700, BAD)
             + T(52, 237, "\"high-impact action needs 2 independent trusted sources, found 1 (wl-01-01)\"", 9, 400, INK2, family=MONO))
    b.append(R(0, 262, 780, 62, STRIP, BLUE, 1.2, 8) + T(12, 282, "A valve or a grid cut waits for a person (brain serve --approvals)", 10.5, 700, BLUE))
    steps = [("alert", "held, with its reason"), ("person", "Approve or Deny on the screen"), ("stamp", "signed, single use, expires"), ("lock", "the gate checks everything again")]
    for i, (ic, t) in enumerate(steps):
        x = 24 + i * 190
        b.append(ICON(ic, x, 306, 20, BLUE, 2.4) + T(x + 16, 310, t, 9.6, 400, INK2))
        if i < 3:
            b.append(ARROW([(x + 168, 306), (x + 182, 306)], BLUE))
    return SVG(780, 332, "".join(b), "The eleven checks of the safety gate")


# --------------------------------------------------------------------------------------------------- figure 9 stack


def fig_stack() -> str:
    items = [
        ("python", "Python 3.12", "the language", "everything"), ("uv", "uv", "locked installs", "Docker image"),
        ("pydantic", "Pydantic", "contracts, policy", "gate, schemas"), ("fastapi", "FastAPI", "API, SSE, screen", "timeline"),
        ("langgraph", "LangGraph", "reflex, team, planner", "SQLite checkpoints"),
        ("langchain", "LangChain", "model agents", "tools, Groq"), ("groq", "Groq", "gpt-oss 120b / 20b", "agents"),
        ("ortools", "OR-Tools", "min-cost flow, CP-SAT", "solvers"), ("networkx", "NetworkX", "city graph", "Neo4j mirror"),
        ("numpy", "NumPy", "forecast, robustness", "solvers"), ("neo4j", "Neo4j", "city graph, on by default", "graph queries"),
        ("qdrant", "Qdrant", "knowledge vectors", "hybrid search"), ("sqlite", "SQLite", "approvals, checkpoints", "gate, planner"),
        ("modelcontextprotocol", "MCP", "the Twin, read-only tools", "partners"), ("mqtt", "MQTT", "a Twin transport", "adapters"),
        ("cloudevents", "CloudEvents", "every timeline event", "screen, log"), ("opentelemetry", "OpenTelemetry", "spans, Jaeger", "evidence"),
        ("docker", "Docker Compose", "the whole city, one command", "make full"), ("threedotjs", "three.js r160", "the canopy, vendored", "screen"),
        ("pytest", "pytest", "1,112 tests", "every change"),
    ]
    b = []
    cw, ch = 150, 78
    for i, (logo, name, role, link) in enumerate(items):
        row, col = divmod(i, 5)
        x, y = col * (cw + 7.5), row * (ch + 8)
        b.append(R(x, y, cw, ch, STRIP, "#C9D0CB", 1.1, 8))
        wide = logo_uri(logo)[1] > 2
        s, w = LOGO(logo, x + 8, y + 8, 18 if wide else 24)
        b.append(s + ("" if wide else T(x + w + 16, y + 26, name, 11, 700)))
        b.append(T(x + 10, y + 52, role, 9.6, 400, INK2) + T(x + 10, y + 66, "feeds: " + link, 8.8, 400, MUTED))
    return SVG(780, 4 * (ch + 8), "".join(b), "The technology stack and what each part feeds")


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
*{box-sizing:border-box}html,body{margin:0;background:#fff;color:#111417;font-family:B612,sans-serif}
.page{width:210mm;height:297mm;padding:13mm 12mm 10mm;position:relative;break-after:page;overflow:hidden}
.page:last-child{break-after:auto}
.top{display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid #111417;padding-bottom:2mm;margin-bottom:4mm;font-size:8.2pt;color:#636B6F}
.top b{color:#111417;letter-spacing:.06em;text-transform:uppercase;font-size:8pt}
h1{font-size:19pt;margin:0 0 1.5mm;line-height:1.15}h2{font-size:12.2pt;margin:3.2mm 0 1.2mm}h3{font-size:10pt;margin:2.5mm 0 1mm}
p{font-size:8.9pt;line-height:1.42;margin:0 0 2mm;color:#2a3033;max-width:70em}
.lede{font-size:10pt;color:#111417}
svg{width:100%;height:auto;display:block;margin:2mm 0}
.cap{font-size:7.8pt;color:#636B6F;margin:0 0 2.5mm}
table{border-collapse:collapse;width:100%;font-size:7.9pt;margin:1.5mm 0 2.5mm}
th{background:#111417;color:#fff;text-align:left;padding:1.3mm 1.8mm;font-weight:700}
td{border-bottom:1px solid #D5DAD5;padding:1.2mm 1.8mm;vertical-align:top;line-height:1.35}
code{font-family:'B612 Mono',monospace;font-size:7.6pt;background:#EEF1ED;padding:0 .8mm}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:5mm}
.rule{display:grid;grid-template-columns:7mm 1fr;gap:2mm;align-items:start;margin-bottom:1.6mm}
.rule svg{width:7mm;margin:0}.rule p{margin:0}
.foot{position:absolute;left:12mm;right:12mm;bottom:6mm;display:flex;justify-content:space-between;font-size:7.4pt;color:#636B6F;border-top:1px solid #D5DAD5;padding-top:1.5mm}
@media screen{html,body{background:#CDD2CD}.page{margin:8mm auto;box-shadow:0 2px 10px rgba(17,20,23,.25);background:#fff}}
.pill{display:inline-block;font-size:7.4pt;font-weight:700;border:1px solid currentColor;padding:0 1.4mm;margin-right:1mm}
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
    return (f"<section class='page'><div class='top'><b>TSYP14 · City Brain layer</b><span>{part}</span></div>{body}"
            f"<div class='foot'><span>City Brain · integration of the parts of one system</span><span>{n}</span></div></section>")


def small_icon(name: str, tone: str) -> str:
    return f"<svg viewBox='0 0 48 48' aria-hidden='true'>{ICON(name, 24, 24, 34, tone, 3)}</svg>"


def rule(name: str, tone: str, text: str) -> str:
    return f"<div class='rule'>{small_icon(name, tone)}<p>{text}</p></div>"


LOGO_CSS = """
.lg{--panel:#fff;--fg:#111417;--muted:#3F464A;--line:#AEB5AF;--steel:#1B49CF;--ember:#A85F00;--wash:#F2F4F1;--body:'Liberation Sans',Arial,Helvetica,sans-serif;--mono:'B612 Mono',monospace}
.lg .card,.lg .card.new{fill:var(--panel);stroke:var(--line);stroke-width:1.4}.lg .card.partner{stroke-dasharray:6 4;stroke:var(--muted);fill:var(--wash)}
.lg .card.gate{stroke:var(--ember);stroke-width:2.6;fill:#FBF1E2}.lg .tile{fill:#fff;stroke:#D5DCE1;stroke-width:1}
.lg .glyph{fill:none;stroke:var(--steel);stroke-width:2.6;stroke-linecap:round;stroke-linejoin:round}.lg .frame{fill:none;stroke:var(--line);stroke-width:1.2;stroke-dasharray:2 5}
.lg .arrow{fill:none;stroke:var(--steel);stroke-width:1.8}.lg .arrow.ember{stroke:var(--ember)}.lg .headfill{fill:var(--steel)}.lg .headember{fill:var(--ember)}
.lg .t{font:700 17px var(--body);fill:var(--fg)}.lg .s{font:400 14px var(--body);fill:var(--muted)}.lg .an{font:400 11px var(--mono);fill:var(--steel)}
.lg.big .t{font-size:20px}.lg.big .s{font-size:16px}.lg.big .k{font-size:13.5px}.lg.small .s{font-size:13px}.lg .k{font:400 11.5px var(--mono);fill:var(--muted);letter-spacing:.04em}
.stats{display:grid;grid-template-columns:repeat(6,1fr);gap:2mm;margin:2.5mm 0 1mm}
.stats div{border:1px solid #AEB5AF;border-top:3px solid #1B49CF;padding:1.6mm 2mm}.stats b{display:block;font-size:13pt;line-height:1.1}.stats span{font-size:7.1pt;color:#636B6F;line-height:1.25;display:block}
h1 small{font-size:10pt;color:#636B6F;font-weight:400;margin-left:2mm}
"""


def logo_fig(svg: str, height: int, size: str = "") -> str:
    """One of docs/diagrams/logo_architecture.py's drawings, cut to its content (the drawings are 1240 wide with room to spare below)."""
    import re
    svg = re.sub(r'viewBox="[^"]*" width="\d+" height="\d+"', f'viewBox="0 0 1240 {height}"', svg, count=1)
    return f"<div class='lg {size}'>{svg}</div>"


def part2(n: int) -> list[str]:
    """Part 2, five pages in the six subheadings the Phase 1 book asks of every layer. n is the first page number."""
    p = []
    p.append(page(n, "Part 2 · The City Brain · 2.1 Role and goals", f"""
<h1>2. The City Brain <small>What should we do?</small></h1>
<h2 style='margin-top:1mm'>2.1 Role and goals</h2>
<p class='lede'>The Brain watches the Twin&rsquo;s live readings, detects real incidents (crimes, fires, accidents, jams, floods, overloads), asks the Guardian whether each reading can be believed, decides the response and acts through the Twin&rsquo;s actuators. It never acts on a reading the Guardian has not vouched for, and it never acts except through one checked door, the <b>safety gate</b>.</p>
{logo_fig(big_picture(), 540, 'big')}
<p class='cap'>Figure 2.1. The Brain between its partners, one protocol on each link. Dashed cards are the other teams&rsquo; layers; the amber card is the gate, the only path to the city.</p>
<div class='cols'><div>
{rule('shield', GOOD, '<b>Trust before action.</b> Every actuator call names a trusted Guardian verdict that covers its evidence (<code>trust_ref</code>).')}
{rule('lock', BLUE, '<b>One way out.</b> Rules, agents and solvers only propose; the gate checks, signs and sends.')}
</div><div>
{rule('check', GOOD, '<b>Code disposes.</b> A model may reason, code verifies; a scripted team passes every scenario with no network.')}
{rule('eye', INK, '<b>Nothing is silent.</b> A held action, a refused reading, an outage: each is a named event with its reason.')}
</div></div>
<div class='stats'>
<div><b>5 / 5</b><span>Test Book scenarios T12&ndash;T16 pass, one chained log each</span></div>
<div><b>3.5 ms</b><span>reflex answer after the evidence (t14)</span></div>
<div><b>1,112</b><span>tests, named as sentences</span></div>
<div><b>24 / 24</b><span>red-team attacks refused</span></div>
<div><b>60 / 60</b><span>held-out variants decide as their base</span></div>
<div><b>19</b><span>conformance checks a partner can run</span></div>
</div>
<h3>Six departments, one per kind of incident</h3>
<table><tr><th>Department</th><th>Incidents</th><th>Acts through</th><th>Reasoning</th></tr>
<tr><td>Police</td><td>crime</td><td><code>dispatch_unit</code> (pursuit, contain), <code>broadcast_alert</code>, <code>recall_unit</code></td><td>team: Analyst, Tactician, Chief</td></tr>
<tr><td>Fire, Ambulance</td><td>fire, accident</td><td><code>dispatch_unit</code>, <code>broadcast_alert</code></td><td>desk: Analyst, Chief</td></tr>
<tr><td>Traffic control</td><td>jam, ambulance route</td><td><code>set_signal_phase</code> (hold green)</td><td>desk</td></tr>
<tr><td>Disaster response</td><td>flood</td><td><code>broadcast_alert</code>, <code>set_valve_state</code> (a person approves)</td><td>desk</td></tr>
<tr><td>Utilities</td><td>overload, smog</td><td><code>broadcast_alert</code>, <code>set_grid_connection</code> (a person approves)</td><td>desk</td></tr></table>
<p>A department is three files (a manifest of detectors and actuators, reflex rules, a playbook), so a new kind of incident is a new pack, not new code.</p>
"""))
    p.append(page(n + 1, "Part 2 · 2.2 Architecture · detection and decision", f"""
<h2 style='margin-top:0'>2.2 Architecture</h2>
<p class='lede'>One reading travels eighteen steps from the Twin to an action and an explanation. Each step is a small part with one job that hands its result to the next; each card names the technology that runs it and, in blue, the brain function it is modelled on (brain-inspired engineering, not a model of a brain).</p>
{logo_fig(incident_flow(), 596)}
<p class='cap'>Figure 2.2. From a reading to a decision. Amber arrows are the way out: reflex proposals reach the gate at once, the team&rsquo;s plan follows and meets the same gate. A plan the team makes the same way twice returns as a reflex after sleep.</p>
<div class='cols'><div>
<h3>Incident detection</h3>
<p><b>Perception</b> checks the contract version, the HMAC signature, the sequence number (replay) and value ranges; a refusal has a code. <b>The Guardian&rsquo;s verdict</b> (2 s deadline) decides whether the reading may count. <b>Forward models</b> learn each sensor&rsquo;s own normal from trusted readings only: a reading many spreads away is a <i>surprise</i> and the reflex it would trigger is held until a second source agrees; a Kalman tracker forecasts when a river reaches the flood line. <b>Triage</b> runs the six departments&rsquo; detectors to open or join an incident, and the <b>workspace</b> gives two seats of attention by severity, trust, surprise and urgency.</p>
<p>Instead of staying silent the Brain says <code>brain.human.needed</code> for an alarm no department knows, an incident with no procedure, or an incident that stalls.</p>
</div><div>
<h3>Decision method: rules, agents and solvers, joined</h3>
<p><b>Rules</b> (13, in six packs) answer in milliseconds with no model. <b>Agent teams</b> weigh the case: for Police an Analyst, a Tactician and a Chief on LangGraph (Groq models with <code>--llm</code>, a scripted stand-in otherwise or when the model fails); the other departments use a two-role desk. <b>Solvers</b> compute what judgement should not guess (OR-Tools min-cost flow for dispatch, CP-SAT for a perimeter and for load shedding, Dijkstra for a green corridor, Kalman for the flood forecast). They run in code before the agents and their answers are written into the brief, so a model that never calls a tool still reads them.</p>
<p>Code then verifies the agents&rsquo; plan (<code>verify_case</code>, <code>verify_plan</code>, <code>verify_desk</code>) before it reaches the gate.</p>
</div></div>
<h3>What can stop a reading on its way to an incident, and what is said</h3>
<table><tr><th style='width:34%'>The reading</th><th style='width:36%'>Event on the timeline</th><th>Shown by</th></tr>
<tr><td>has a bad signature, a replayed sequence number or a value out of range</td><td><code>brain.reading.rejected</code> with a stable code</td><td><code>brain redteam</code>, <code>brain conformance</code></td></tr>
<tr><td>is judged untrusted by the Guardian</td><td><code>brain.action.blocked</code> (trust), nothing is sent</td><td>T13, T15</td></tr>
<tr><td>jumps further than its own history explains</td><td><code>brain.percept.surprise</code>, the reflex is held</td><td><code>brain forward-bench</code></td></tr>
</table>
<p><b>Two speeds, one gate.</b> In T14 the reflex dispatches the first unit 3.5 ms after the evidence; the team&rsquo;s solver-checked perimeter follows about 70 ms later and passes the same eleven checks.</p>
"""))
    p.append(page(n + 2, "Part 2 · 2.2 Architecture · how it picks an actuator", f"""
<h2 style='margin-top:0'>2.2 Architecture (continued): how the Brain picks an actuator</h2>
<p class='lede'>Three steps: the incident type decides which department may act and with which actuator; a solver or the nearest free station picks the device; the gate decides whether the call may go. The Brain never calls the Twin from anywhere else.</p>
{logo_fig(planner(), 566)}
<p class='cap'>Figure 2.3. The planning graph for one incident (LangGraph): solve and deliberate in parallel, keep the better plan, pause for a person on a valve or the grid, checkpoint to SQLite so a run resumes and replays.</p>
<div class='cols'><div>
<h3>Which station or device</h3>
<p>Nearest free station by hop distance, never a quarantined or reserved one (scenario T16: the Guardian quarantines a station, the gate refuses it with reason <code>quarantine</code> and another is sent). When two incidents want the same kind of unit, the dispatch solver solves them together and its choice is used only if it saves cost: for two collisions the far ambulance goes to the first so the near one is free for the second (2.8 against 4.2).</p>
</div><div>
<h3>Which cut, which signal</h3>
<p>A cascade analysis weighs what each grid cut would darken (a hospital counts 10) and the shed solver picks the cheapest set that removes the excess. A corridor holds the signals on an ambulance&rsquo;s route green. A dispatched unit&rsquo;s <code>unit_status</code> readings close the incident; an arrest recalls every unit still out.</p>
</div></div>
{fig_gate()}
<p class='cap'>Figure 2.4. The safety gate. Every proposal, from a rule, an agent or a solver, meets the same eleven checks in order; the first that fails stops the call and is logged with its reason. A repeated call returns <code>duplicate</code> from the Twin.</p>
"""))
    p.append(page(n + 3, "Part 2 · 2.3 Tech stack and why · 2.4 Interfaces in/out", f"""
<h2 style='margin-top:0'>2.3 Tech stack and why</h2>
<p>Standard, well-known parts, each with one job. The stack runs offline on one laptop: the embedding model is baked into the image, the screen loads nothing from the internet, and a model outage only changes who reasons.</p>
{fig_stack()}
<p class='cap'>Figure 2.5. The stack and what each part feeds. Logos identify the technologies; each belongs to its owner.</p>
<table><tr><th style='width:24%'>Choice</th><th>Why</th></tr>
<tr><td>Python 3.12, uv, Pydantic</td><td>One language for rules, agents and solvers; locked, reproducible builds; every message a typed model that validates itself.</td></tr>
<tr><td>LangGraph + OR-Tools</td><td>Graphs that pause, resume and checkpoint for agents; proven solvers with a certificate for what must be exact.</td></tr>
<tr><td>MCP, REST, SSE + CloudEvents</td><td>MCP gives the Twin&rsquo;s tools schemas and discovery; REST is one question, one answer for verdicts; SSE is one-way, replayable, and needs no client library.</td></tr>
<tr><td>Neo4j + Qdrant</td><td>The city as a graph that answers &ldquo;why was this unit sent?&rdquo; in one query; hybrid search over 39 procedures. Decisions never wait on either.</td></tr></table>
<h2>2.4 Interfaces in/out</h2>
<table><tr><th style='width:16%'>Direction</th><th style='width:32%'>Message</th><th>Transport (default first) and contract</th></tr>
<tr><td>In, from the Twin</td><td>signed sensor readings; the city layout</td><td>MCP <code>list_readings(cursor)</code> every 200 ms and <code>get_topology()</code>; also plain HTTP or MQTT</td></tr>
<tr><td>In, from the Guardian</td><td>a signed trust verdict per reading; its containment list</td><td>with the Guardian team&rsquo;s contract 1.0: REST <code>POST /v1/verdicts/request</code> (by sensor and sequence number), HMAC checked; <code>GET /v1/containment</code>; <code>X-API-Key</code>. The Brain asks; it does not read the alert feed <code>WS /v1/ws/verdicts</code>. Our mock speaks a simpler REST contract (<code>POST /verdicts</code>)</td></tr>
<tr><td>Out, to the Twin</td><td>signed calls: <code>dispatch_unit</code>, <code>broadcast_alert</code>, <code>recall_unit</code>, <code>set_signal_phase</code>, <code>set_valve_state</code>, <code>set_grid_connection</code></td><td>valve, grid, signal and dispatch go through the Guardian&rsquo;s audited <code>POST /v1/actuator-calls</code>; broadcast and recall, which its registry does not list, go to the Twin directly (MCP tool of the same name, or HTTP)</td></tr>
<tr><td>Out, to anyone</td><td>timeline events; the why of a decision; read-only tools</td><td>SSE <code>GET /events</code> (CloudEvents 1.0, 55 types in AsyncAPI); <code>/api/decisions/{{id}}/explanation</code>; MCP at <code>/mcp</code></td></tr></table>
<p>All of it is in the one-page Interface Card (<code>brain/INTERFACE.md</code>) with a JSON example of every message and JSON Schemas in <code>contracts/</code>. A new partner is an edit of <code>config/partners.yaml</code> (address, adapter, secret names, renames, units), never a code change: decision code reaches partners only through two ports, and <code>tests/test_layering.py</code> fails the build if it imports a protocol.</p>
"""))
    p.append(page(n + 4, "Part 2 · 2.5 Security measures · 2.6 Known limitations", f"""
<h2 style='margin-top:0'>2.5 Security measures</h2>
<p class='lede'>Every input is hostile until checked, every model answer is a suggestion, and the only way out is one signed call that a person approves when it is high-impact. Threats are mapped to MITRE ATT&amp;CK for ICS and to MITRE ATLAS for the AI parts (<code>docs/SECURITY-MITRE.md</code>).</p>
{logo_fig(defence(), 152, 'small')}
<p class='cap'>Figure 2.6. Six layers, each assuming the one outside it can fail.</p>
<table style='font-size:7.4pt'><tr><th style='width:20%'>Boundary</th><th>Control</th></tr>
<tr><td>Twin to Brain: readings</td><td>HMAC-SHA256 or Ed25519 over canonical JSON, key ids with expiry, a rising sequence number per sensor, schema and ranges; only allowlisted fields are kept, so demographic fields never reach a decision</td></tr>
<tr><td>Guardian to Brain: verdicts</td><td>schema check; the gate asks for more independent trusted sources as impact rises; only the Guardian&rsquo;s token may retract a verdict; the 1.0 adapter checks the verdict&rsquo;s HMAC</td></tr>
<tr><td>People, partners to the API</td><td>scoped bearer tokens off loopback (read, push, approve, admin), body and rate limits; a partner may push only <code>twin.*</code> or <code>guardian.*</code> events, a forged <code>brain.*</code> is refused</td></tr>
<tr><td>Brain to the language model</td><td>ids limited to safe characters before any prompt; read-only tools, no actuating tool exists; models pick zone ids, never free text; code verifies; then the gate</td></tr>
<tr><td>Brain to Twin: calls</td><td>eleven gate checks; each call signed with its time and a one-time nonce; a valve or grid call needs a signed approval bound to its exact parameters, used once</td></tr>
<tr><td>Brain to its own disk</td><td>hash-chained log with a signed head; learning only from trusted readings; self-tuning limited to a listed set of numbers, each with a range</td></tr></table>
<table style='font-size:7.4pt'><tr><th style='width:26%'>MITRE technique</th><th style='width:46%'>Attack run against the code</th><th>Result</th></tr>
<tr><td>ICS T1692.002 forged reading</td><td>wrong key, no signature, a field edited after signing, a replayed sequence number, <code>alg: none</code></td><td>refused every time</td></tr>
<tr><td>ICS T1692.001, T0849 forged call</td><td>an approval reused with changed parameters; the Twin pushing as the Guardian</td><td>refused</td></tr>
<tr><td>Enterprise T1190, T1078</td><td>no token, a forged token, a read token doing admin work, 28 path spellings by 7 methods</td><td>none got through</td></tr>
<tr><td>ATLAS AML.T0051, T0053</td><td>30 prompt-injection strings in sensor ids and values; a tool that tries to actuate</td><td>dropped before any prompt; no such tool can exist</td></tr></table>
<p><b>Evidence.</b> <code>brain redteam</code>: 24 attacks, all refused (re-run for this report). A partner&rsquo;s bad message is answered with a stable code and a sentence (<code>signature_invalid</code>, <code>replay_or_out_of_order</code>, <code>value_invalid</code>&hellip;) and shown on the timeline. A silent Guardian gives no verdict, so nothing it has not judged is acted on (T15): the Guardian&rsquo;s fail-safe rule, enforced on the Brain&rsquo;s side too.</p>
<h2>2.6 Known limitations</h2>
<div class='cols'><div>
{rule('plug', BAD, '<b>No joint run with the real Twin yet.</b> End to end only against mocks; against the live Guardian, the fake and real flood and T16 (<code>logs/t16-live-guardian-*.log</code>).')}
{rule('shield', WARN, '<b>The mock Guardian is scripted.</b> T13 and T16 show what the Brain does <i>given</i> a verdict, not whether a real Guardian would give it.')}
{rule('alert', WARN, '<b>Our mock&rsquo;s contract does not sign verdicts.</b> The Guardian team&rsquo;s 1.0 does, and the Brain checks it.')}
{rule('dial', MUTED, '<b>Tuned on stand-ins.</b> Which sensors move together, and whether same-zone sensors are independent, wait for the real Twin&rsquo;s data (<code>docs/TWIN-HANDOVER.md</code>).')}
</div><div>
{rule('lock', WARN, '<b>TLS and the freshness limit are off by default.</b> Signatures still protect readings and calls; set <code>twin.max_age_s</code> on the live Twin.')}
{rule('route', BAD, '<b>One dispatch per incident at the Guardian.</b> Its auditor refuses a second dispatch for one incident (<code>duplicate_dispatch</code>), so T14&rsquo;s perimeter units would be refused. To agree: a duplicate is the same incident <i>and</i> station.')}
{rule('alert', WARN, '<b>Guardian alerts are not read.</b> An actuator it flags unreliable reaches the Brain through the containment list, which the gate obeys; <code>compromised_twin</code> does not.')}
</div></div>
"""))
    return p


def pages() -> list[str]:
    p = []
    p.append(page(1, "Part 0 · Triplet overview and integration", f"""
<h1>The City Brain inside the triplet</h1>
<p class='lede'>Three layers, one loop. The <b>Twin</b> is the simulated city, the <b>Guardian</b> says which readings can be believed, and the <b>City Brain</b> decides and acts. Figure 1 is the Brain's part of the global diagram: every box is a component that exists and runs, and the arrows are the ways they hand work to each other.</p>
{fig_architecture()}
<p class='cap'>Figure 1. Global architecture. Readings enter at the top and actions leave only through the gate. The dotted line across the top is the Guardian team&rsquo;s design, where the Twin also feeds the Guardian. Dashed amber arrows show where a solver's answer enters a team's brief; dashed green arrows show the learning loop.</p>
<table><tr><th>Link</th><th>How it talks</th><th>What keeps it safe</th></tr>
<tr><td>Twin to Brain</td><td>MCP tool <code>list_readings</code> (also HTTP and MQTT); city layout from <code>get_topology</code></td><td>contract version, HMAC signature, sequence number, ranges</td></tr>
<tr><td>Brain to Guardian</td><td>REST, 2 s deadline. Our contract: <code>POST /verdicts</code> with the reading, <code>GET /quarantine/{{id}}</code>. The Guardian team&rsquo;s 1.0: <code>POST /v1/verdicts/request</code> by sensor and sequence number, <code>GET /v1/containment</code></td><td>silent Guardian means degraded mode: only low-impact actions pass</td></tr>
<tr><td>Twin to Guardian</td><td>the Guardian team&rsquo;s contract only: the Twin pushes <code>POST /v1/readings</code> (or the Guardian pulls). The Brain is not on this path</td><td>HMAC on every reading; the Guardian checks sequence and timestamp</td></tr>
<tr><td>Brain to Twin</td><td>signed actuator calls through the Twin's MCP tools; with the Guardian team&rsquo;s Guardian, valve, grid, signal and dispatch calls go through its <code>POST /v1/actuator-calls</code>, which audits them before forwarding; results come back as readings and <code>unit_status</code></td><td>the gate: 11 checks, trust reference, idempotency, human approval</td></tr>
<tr><td>Any partner to the screen</td><td>CloudEvents over SSE; a partner may push <code>twin.*</code> or <code>guardian.*</code> events</td><td><code>brain.*</code> pushes are refused; scoped tokens off loopback</td></tr></table>
"""))
    p.append(page(2, "Part 0 · One scenario traced end to end", f"""
<h1>One scenario, end to end: crime and pursuit</h1>
<p class='lede'>A robbery is caught on camera in Downtown (scenario <code>t14</code>). The trace below is from a real run at normal speed; times are measured from the first reading. Read it left to right: the same event is touched by every layer and by most components of the Brain, and each hand-off is an event on the timeline.</p>
{fig_trace()}
<p class='cap'>Figure 2. The reflex tier answers 3.5 ms after the evidence arrives; the team's fuller plan follows about 70 ms later and passes the same gate. The perimeter solver checks the team's plan (2 units hold, 2 are used).</p>
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
{rule('chart', INK, '<b>Evidence, not claims.</b> 1,112 tests, 5 Test Book scenarios, 50 held-out variants, a hash-chained log per run, and <code>brain rehearse</code> as the freeze check.')}
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
<tr><td><b>Validation and clear errors</b></td><td>Every reading is checked on entry; a refusal carries a code and a reason (below) and goes to the timeline. A bad verdict puts the Brain in degraded mode; a failing Twin tool is named in the error.</td><td><code>brain conformance</code> checks a real partner; <code>brain redteam</code>: 24 attacks, all refused.</td></tr></table>
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
    for family, weight, file in (("B612", 400, "B612-Regular.woff2"), ("B612", 700, "B612-Bold.woff2"),
                                 ("B612 Mono", 400, "B612Mono-Regular.woff2"), ("B612 Mono", 700, "B612Mono-Bold.woff2")):
        src = "data:font/woff2;base64," + base64.b64encode((FONTS / file).read_bytes()).decode() if embed_fonts else (FONTS / file).as_uri()
        faces += f"@font-face{{font-family:'{family}';font-weight:{weight};src:url('{src}') format('woff2')}}"
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
