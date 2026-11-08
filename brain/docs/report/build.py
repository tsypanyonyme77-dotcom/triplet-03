"""The City Brain's parts of the Phase 1 report, as one vector PDF and one self-contained HTML page.

    uv run python docs/report/build.py        # docs/report/report-city-brain.pdf and docs/report/report-city-brain.html

Part 0 (the Brain in the triplet), Part 2 (the City Brain) and Part 4 (the Test Book), eleven A4 pages. Every figure is drawn here as SVG
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
from logo_architecture import GLYPHS, logo_uri  # noqa: E402

FONTS = ROOT / "src/brain/api/static/fonts"
PDF, PAGE = HERE / "report-city-brain.pdf", HERE / "report-city-brain.html"

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
    b.append(LINES(705, 246, ["a verdict on", "every reading", "(trusted, suspicious,", "untrusted)", "", "a quarantine list", "of actuators"], 10, 14, INK2, "middle"))
    # Brain frame
    b.append(R(190, 14, 420, 656, BOARD, INK, 2, 12))
    b.append(T(204, 34, "City Brain layer", 13, 700) + T(594, 34, "every arrow is an event on the timeline", 9, 400, MUTED, "end"))
    X1, X2, X3, W3, WF = 204, 332, 460, 126, 382
    y1, y2, y3, y4, yg, y6 = 46, 124, 232, 320, 436, 512
    b.append(NODE(X1, y1, WF, 62, "Ports and adapters", ["MCP, HTTP or MQTT in; REST to the Guardian"], "plug", BLUE, ("modelcontextprotocol", "mqtt")))
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
    return SVG(780, 700, "".join(b), "Global architecture: Twin, City Brain and Guardian")



# --------------------------------------------------------------------------------------------------- figure: the line between logic and partners


def fig_interop() -> str:
    b = []
    b.append(R(0, 10, 100, 152, STRIP, INK, 1.4, 9, "5 3") + BADGE("city", 50, 40, 34, MUTED) + T(50, 76, "Twin", 12.5, 700, INK, "middle") + LINES(50, 94, ["any engine that", "speaks the card"], 9, 12, MUTED, "middle"))
    b.append(R(680, 10, 100, 152, STRIP, INK, 1.4, 9, "5 3") + BADGE("shield", 730, 40, 34, GOOD) + T(730, 76, "Guardian", 12.5, 700, INK, "middle") + LINES(730, 94, ["any service that", "issues a verdict"], 9, 12, MUTED, "middle"))
    b.append(NODE(130, 10, 138, 152, "Twin adapters", ["one class each:", "MCP (default),", "HTTP, MQTT", "", "protocol, TLS and", "retries stay here"], "plug", BLUE, ("modelcontextprotocol", "mqtt")))
    b.append(NODE(512, 10, 138, 152, "Guardian adapter", ["REST, one class", "", "a bad or late", "verdict becomes", "degraded mode,", "never a crash"], "plug", BLUE))
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


# --------------------------------------------------------------------------------------------------- figure 3 loops


def fig_loops() -> str:
    b = []
    bands = [
        (0, "Inner loop: one reading", "milliseconds", BLUE, [("eye", "sense"), ("shield", "trust"), ("dial", "predict"), ("route", "triage"), ("bolt", "reflex"), ("lock", "gate"), ("unit", "act")]),
        (118, "Task loop: one incident's team", "seconds, 30 s budget", INK, [("file", "brief + facts"), ("agents", "Analyst"), ("agents", "Chief"), ("check", "code verifies"), ("lock", "gate")]),
        (236, "Meta loop: between runs", "minutes to days", GOOD, [("db", "episodes"), ("loop", "sleep"), ("stamp", "promote"), ("dial", "Academy tunes")]),
    ]
    for y, title, sub, tone, steps in bands:
        b.append(R(0, y, 780, 100, WASH[tone], tone, 1.2, 10))
        b.append(T(14, y + 20, title, 12.5, 700, tone) + T(766, y + 20, sub, 10, 400, MUTED, "end"))
        n = len(steps)
        for i, (ic, label) in enumerate(steps):
            x = 70 + i * (640 / max(n - 1, 1)) if n > 1 else 390
            b.append(BADGE(ic, x, y + 56, 40, tone) + T(x, y + 90, label, 10, 700, INK, "middle"))
            if i < n - 1:
                nx = 70 + (i + 1) * (640 / (n - 1))
                b.append(ARROW([(x + 24, y + 56), (nx - 24, y + 56)], tone, width=1.5))
    b.append(ARROW([(390, 100), (390, 118)], BLUE, "an incident needs a team", 396, 113, anchor="start"))
    b.append(ARROW([(640, 218), (640, 236)], GOOD, "a closed incident becomes an episode", 634, 232, anchor="end"))
    b.append(ARROW([(120, 336), (120, 346), (30, 346), (30, 70), (36, 70)], GOOD, dash="4 3"))
    b.append(T(14, 366, "A promoted lesson comes back as a reflex in the inner loop (learning curve of t14: team runs 1 to 0, last action 94.7 ms to 35.5 ms).", 9.5, 400, INK2))
    return SVG(780, 376, "".join(b), "Three loops: inner, task and meta")


# --------------------------------------------------------------------------------------------------- figure 4 detection


def fig_detection() -> str:
    stages = [
        ("shield", "Perception", GOOD, ["contract version,", "HMAC, replay,", "value ranges"], "refused with a code", "brain.reading.rejected"),
        ("eye", "Guardian verdict", GOOD, ["trusted, suspicious,", "untrusted; a score", "built on untrusted", "evidence is damped"], "t13: a lying gauge is refused", "nothing is sent"),
        ("dial", "Forward models", GOOD, ["each sensor's own normal", "coupled sensors,", "level forecast"], "a gauge jumps 70 spreads (forward-bench)", "the reflex is held"),
        ("route", "Triage", INK, ["six packs' detectors", "crime triggers", "alarms no pack knows"], "a riot, a call 'other'", "a person is asked"),
        ("eye", "Workspace", INK, ["salience: severity,", "trust, evidence, surprise,", "urgency; two seats"], "a rising river (unit test)", "takes the seat"),
    ]
    b = []
    w = 148
    for i, (ic, name, tone, rows, example, outcome) in enumerate(stages):
        x = i * (w + 10)
        b.append(R(x, 0, w, 238, STRIP, tone, 1.3, 9))
        b.append(BADGE(ic, x + 28, 32, 38, tone) + T(x + 52, 36, name, 11.5, 700))
        b.append(LINES(x + 12, 68, rows, 9.6, 12.5))
        b.append(R(x + 8, 140, w - 16, 44, WASH[tone], tone, 0.8, 5))
        b.append(T(x + 14, 156, "stops or flags", 8.6, 700, tone) + LINES(x + 14, 169, [example], 8.8, 0, INK))
        b.append(R(x + 8, 192, w - 16, 36, WASH[BAD] if "held" in outcome or "nothing" in outcome or "asked" in outcome else WASH[GOOD], BAD if "held" in outcome or "nothing" in outcome or "asked" in outcome else GOOD, 0.8, 5))
        b.append(T(x + 14, 208, "result", 8.6, 700, MUTED) + T(x + 14, 221, outcome, 9, 700, INK))
        if i < 4:
            b.append(ARROW([(x + w + 1, 119), (x + w + 9, 119)], INK))
    b.append(T(0, 262, "A reading that survives every stage opens or joins an incident. The three flags on the right never act alone: each is a named event on the screen.", 10, 400, INK2))
    return SVG(780, 272, "".join(b), "Incident detection: five stages and what each can stop")


# --------------------------------------------------------------------------------------------------- figure 5 decision


def fig_decision() -> str:
    b = []
    L = 138
    b.append(NODE(0, 70, 120, 74, "Incident", ["opened by triage,", "lit by workspace"], "route", INK))
    # reflex lane
    b.append(R(L, 0, 780 - L, 70, WASH[BLUE], BLUE, 1.1, 9) + T(L + 12, 18, "Reflex tier  ·  about 4 ms, no model", 10.5, 700, BLUE))
    for k, (ic, t) in enumerate((("bolt", "Rule matches"), ("unit", "Station choice"), ("file", "ProposedAction"))):
        b.append(NODE(L + 12 + k * 206, 28, 190, 34, t, [], ic, BLUE))
        if k < 2:
            b.append(ARROW([(L + 12 + k * 206 + 190, 45), (L + 12 + (k + 1) * 206, 45)], BLUE))
    # team lane
    b.append(R(L, 80, 780 - L, 160, WASH[INK], INK, 1.1, 9) + T(L + 12, 98, "Team tier  ·  about 70 ms scripted, seconds with a model, 30 s budget", 10.5, 700, INK))
    names = (("file", "Brief", "incident + facts"), ("agents", "Analyst", "read-only tools"), ("agents", "Tactician", "options"), ("agents", "Chief", "decides"), ("check", "Verify", "code checks"))
    for k, (ic, t, sub) in enumerate(names):
        x = L + 12 + k * 124
        b.append(NODE(x, 108, 112, 54, t, [sub], ic, GOOD if t == "Verify" else INK))
        if k < 4:
            b.append(ARROW([(x + 112, 135), (x + 124, 135)], INK))
    # solver band
    b.append(R(L + 12, 172, 780 - L - 24, 58, WASH[WARN], WARN, 1, 7) + T(L + 22, 189, "Solvers, run in code before the Analyst; their answers are the brief's facts", 9.6, 700, WARN))
    for k, (ic, t) in enumerate((("route", "dispatch"), ("scale", "perimeter"), ("bolt", "shed + cascade"), ("dial", "forecast"), ("signal", "corridor"))):
        x = L + 34 + k * 118
        b.append(ICON(ic, x, 212, 18, WARN, 2.4) + T(x + 14, 216, t, 9.2, 400, INK2))
    b.append(ARROW([(L + 68, 172), (L + 68, 162)], WARN, dash="4 3"))
    # gate
    b.append(NODE(L, 262, 780 - L, 52, "Safety gate", ["checks, signs, sends; a refusal is an event with its reason"], "lock", BLUE, accent=True))
    b.append(ARROW([(120, 107), (L, 107)], INK))
    b.append(ARROW([(L + 12 + 3 * 206 - 6, 62), (770, 62), (770, 262)], BLUE, "reflex proposals", 764, 254, anchor="end"))
    b.append(ARROW([(450, 240), (450, 262)], BLUE, "team proposals", 458, 256, anchor="start"))
    b.append(T(0, 338, "Rules act first and the team follows with a fuller plan; both pass the same gate. If a model fails, a scripted stand-in answers the same role (brain.agent.fallback).", 9.8, 400, INK2))
    return SVG(780, 348, "".join(b), "Decision pipeline: reflex tier, team tier, solvers and the gate")


# --------------------------------------------------------------------------------------------------- figure 6 matrix


def fig_matrix() -> str:
    teams = [("shield", "Police", MUTED), ("flame", "Fire", BAD), ("cross", "Ambulance", BAD), ("signal", "Traffic", BLUE), ("waves", "Disaster", BLUE), ("bolt", "Utilities", WARN)]
    tools = [
        ("bolt", "Reflex rules", "13 rules in six packs", INK, ["R", "R", "R", "R", "R", "R"], ()),
        ("book", "Playbook search", "39 procedures", MUTED, ["T", "T", "T", "T", "T", "T"], ("qdrant",)),
        ("db", "City graph tools", "context, evidence", MUTED, ["T", "T", "T", "T", "T", "T"], ("neo4j",)),
        ("route", "Dispatch solver", "min-cost flow", WARN, ["R", "F", "F", "", "", ""], ("ortools",)),
        ("scale", "Perimeter solver", "CP-SAT + critic", WARN, ["F", "", "", "", "", ""], ("ortools",)),
        ("bolt", "Shed and cascade", "CP-SAT", WARN, ["", "", "", "T", "T", "F"], ("ortools",)),
        ("dial", "Level forecast", "Kalman", WARN, ["", "", "", "", "F", "T"], ()),
        ("signal", "Corridor planner", "Dijkstra", WARN, ["", "S", "S", "F", "", ""], ()),
    ]
    b = []
    x0, cw, rh = 200, 92, 44
    for j, (ic, name, tone) in enumerate(teams):
        x = x0 + j * cw + cw / 2
        b.append(BADGE(ic, x, 24, 32, tone) + T(x, 54, name, 10, 700, INK, "middle"))
    for i, (ic, name, sub, tone, cells, logos) in enumerate(tools):
        y = 68 + i * rh
        b.append(R(0, y, 780, rh - 4, WASH.get(tone, "#F7F8F6") if i % 2 == 0 else STRIP, "#DDE1DC", 0.8, 5))
        b.append(ICON(ic, 20, y + 20, 20, tone, 2.4) + T(40, y + 18, name, 10.8, 700) + T(40, y + 31, sub, 9, 400, MUTED))
        if logos:
            b.append(LOGOS(logos, 138, y + 10, 14))
        for j, c in enumerate(cells):
            x = x0 + j * cw + cw / 2
            cy = y + 19
            if c == "F":
                b.append(f"<circle cx='{x}' cy='{cy}' r='8' fill='{WARN}'/>")
            elif c == "T":
                b.append(f"<circle cx='{x}' cy='{cy}' r='7' fill='none' stroke='{INK2}' stroke-width='1.8'/>")
            elif c == "R":
                b.append(f"<rect x='{x - 7}' y='{cy - 7}' width='14' height='14' fill='{BLUE}'/>")
            elif c == "S":
                b.append(f"<path d='M{x - 8} {cy + 7}L{x} {cy - 8}L{x + 8} {cy + 7}z' fill='{GOOD}'/>")
    ly = 68 + len(tools) * rh + 6
    b.append(f"<circle cx='10' cy='{ly}' r='7' fill='{WARN}'/>" + T(24, ly + 4, "the answer is written into the team's brief", 9.6, 400, INK2))
    b.append(f"<circle cx='290' cy='{ly}' r='6' fill='none' stroke='{INK2}' stroke-width='1.8'/>" + T(302, ly + 4, "a read-only tool the agent may call", 9.6, 400, INK2))
    b.append(f"<rect x='513' y='{ly - 7}' width='14' height='14' fill='{BLUE}'/>" + T(533, ly + 4, "proposes through the gate", 9.6, 400, INK2))
    b.append(f"<path d='M{660} {ly + 6}L{668} {ly - 7}L{676} {ly + 6}z' fill='{GOOD}'/>" + T(682, ly + 4, "triggers it", 9.6, 400, INK2))
    b.append(T(0, ly + 26, "Beyond the table: the forecast also feeds the workspace (urgency) and the early flood alert; the dispatch solver also chooses every station when incidents compete.", 9.6, 400, INK2))
    return SVG(780, ly + 40, "".join(b), "Which tool serves which team")


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


# --------------------------------------------------------------------------------------------------- figure 8 flows


def fig_flows() -> str:
    cols = [
        ("A fake flood (t13)", WARN, [
            ("drop", "an honest gauge reads 0.3 m; a second says 1.8 m"),
            ("shield", "the Guardian marks the second gauge untrusted"),
            ("route", "the Brain opens a flood incident, evidence untrusted"),
            ("lock", "the gate refuses the warning and the valve call"),
            ("check", "the honest gauge clears it; nothing reaches the city"),
            ("file", "the explanation names the check that held each call")]),
        ("A flood, an attack, a layer down (t15)", BLUE, [
            ("drop", "the water rises while a forged robbery arrives"),
            ("alert", "the forged report is tracked; no police are sent"),
            ("lock", "the valve is held: one trusted source, needs two"),
            ("shield", "the Guardian stops answering after 120 verdicts"),
            ("alert", "the Brain says so once and warns neighbouring zones"),
            ("check", "low-impact alerts only until verdicts return")]),
        ("The model stops answering", BAD, [
            ("key", "Groq answers 401, a daily limit, or nothing"),
            ("alert", "named: key rejected, quota spent, rate limit, network"),
            ("agents", "the very next team call uses the scripted stand-in"),
            ("monitor", "the chip reads 'model down: why'; M forces it by hand"),
            ("clock", "after a cool-down one call tests the model again"),
            ("check", "decisions are unchanged: code still disposes")]),
    ]
    b = []
    for i, (title, tone, steps) in enumerate(cols):
        x = i * 262
        b.append(R(x, 0, 250, 372, WASH[tone], tone, 1.2, 10) + T(x + 12, 22, title, 11, 700, tone))
        for k, (ic, text) in enumerate(steps):
            y = 40 + k * 55
            b.append(BADGE(ic, x + 28, y + 16, 30, tone))
            words = text.split()
            lines, cur = [], ""
            for wd in words:
                if len(cur) + len(wd) + 1 > 33:
                    lines.append(cur)
                    cur = wd
                else:
                    cur = (cur + " " + wd).strip()
            lines.append(cur)
            b.append(LINES(x + 52, y + 12, lines, 9.6, 12, INK))
            if k < 5:
                b.append(ARROW([(x + 28, y + 34), (x + 28, y + 50)], tone, width=1.3))
    return SVG(780, 372, "".join(b), "Three flows in which several components interlock")


# --------------------------------------------------------------------------------------------------- figure 9 stack


def fig_stack() -> str:
    items = [
        ("python", "Python 3.12", "the language", "everything"), ("uv", "uv", "locked installs", "Docker image"),
        ("pydantic", "Pydantic", "contracts, policy", "gate, schemas"), ("fastapi", "FastAPI", "API, SSE, screen", "timeline"),
        ("langgraph", "LangGraph", "reflex, team, planner", "SQLite checkpoints"),
        ("langchain", "LangChain", "model agents", "tools, Groq"), ("groq", "Groq", "gpt-oss 120b / 20b", "agents"),
        ("ortools", "OR-Tools", "min-cost flow, CP-SAT", "solvers"), ("networkx", "NetworkX", "city graph", "Neo4j mirror"),
        ("numpy", "NumPy", "forecast, robustness", "solvers"), ("neo4j", "Neo4j", "graph mirror (optional)", "full stack"),
        ("qdrant", "Qdrant", "knowledge vectors", "hybrid search"), ("sqlite", "SQLite", "approvals, checkpoints", "gate, planner"),
        ("modelcontextprotocol", "MCP", "the Twin, read-only tools", "partners"), ("mqtt", "MQTT", "a Twin transport", "adapters"),
        ("cloudevents", "CloudEvents", "every timeline event", "screen, log"), ("opentelemetry", "OpenTelemetry", "spans, Jaeger", "evidence"),
        ("docker", "Docker Compose", "the whole city, one command", "make full"), ("threedotjs", "three.js r160", "the canopy, vendored", "screen"),
        ("pytest", "pytest", "1,064 tests", "every change"),
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
        ("shield", GOOD, "Guardian silent", "degraded mode: only low-impact calls pass; a score built on unvouched evidence is damped", "t15"),
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


def pages() -> list[str]:
    p = []
    p.append(page(1, "Part 0 · Triplet overview and integration", f"""
<h1>The City Brain inside the triplet</h1>
<p class='lede'>Three layers, one loop. The <b>Twin</b> is the simulated city, the <b>Guardian</b> says which readings can be believed, and the <b>City Brain</b> decides and acts. Figure 1 is the Brain's part of the global diagram: every box is a component that exists and runs, and the arrows are the ways they hand work to each other.</p>
{fig_architecture()}
<p class='cap'>Figure 1. Global architecture. Readings enter at the top and actions leave only through the gate. Dashed amber arrows show where a solver's answer enters a team's brief; dashed green arrows show the learning loop.</p>
<table><tr><th>Link</th><th>How it talks</th><th>What keeps it safe</th></tr>
<tr><td>Twin to Brain</td><td>MCP tool <code>list_readings</code> (also HTTP and MQTT); city layout from <code>get_topology</code></td><td>contract version, HMAC signature, sequence number, ranges</td></tr>
<tr><td>Brain to Guardian</td><td>REST <code>POST /verdicts</code>, 2 s deadline; <code>GET /quarantine/{{id}}</code></td><td>silent Guardian means degraded mode: only low-impact actions pass</td></tr>
<tr><td>Brain to Twin</td><td>signed actuator calls through the Twin's MCP tools; results come back as readings and <code>unit_status</code></td><td>the gate: 11 checks, trust reference, idempotency, human approval</td></tr>
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
<p><b>A fake flood (t13):</b> the Guardian marks the reading untrusted and the gate refuses the warning and the valve call. <b>A layer down (t15):</b> the Guardian stops answering, the Brain says so once and carries on with low-impact alerts only.</p></div></div>
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
{rule('chart', INK, '<b>Evidence, not claims.</b> 1,064 tests, 4 Test Book scenarios, 50 held-out variants, a hash-chained log per run, and <code>brain rehearse</code> as the freeze check.')}
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
<tr><td><b>Validation and clear errors</b></td><td>Every reading is checked on entry; a refusal carries a code and a reason (below) and goes to the timeline. A bad verdict puts the Brain in degraded mode; a failing Twin tool is named in the error.</td><td><code>brain conformance</code> checks a real partner; <code>brain redteam</code>: 22 attacks, all refused.</td></tr></table>
<h2>What a partner is told when it sends something unexpected</h2>
<table style='font-size:7.3pt'><tr><th style='width:21%'>The partner sends</th><th style='width:22%'>Code</th><th>The Brain's answer, as the code returns it</th></tr>
{rejection_rows()}</table>
<p class='cap'>Table 2. Run through the Brain's own perception code when this report is built. Not shown yet: the Brain has run only against mocks of the Twin and the Guardian; the HTTP and MQTT adapters are agreed but not yet run against a partner.</p>
"""))
    p.append(page(5, "Part 2 · The City Brain · overview", f"""
<h1>2. The City Brain: one system, many parts that need each other</h1>
<p class='lede'>The Brain is a decision layer made of parts that each do one small thing and hand their result to the next: a prediction that raises attention, attention that recruits a team, a team that is handed a solver's answer, a gate that checks the team. No part is useful alone, and no part may act alone. This part explains what the parts are and, above all, how they are connected.</p>
{fig_loops()}
<p class='cap'>Figure 3. Three loops at three speeds. The loops are linked: an incident starts a task loop; a closed incident feeds the meta loop; a promoted lesson returns as a reflex.</p>
<h2>Four rules that make the parts safe to connect</h2>
<div class='cols'><div>
{rule('shield', GOOD, '<b>Trust before action.</b> Every call names a trusted Guardian verdict that covers its evidence.')}
{rule('lock', BLUE, '<b>The gate is the only way out.</b> Rules, agents and solvers propose; only the gate signs.')}
</div><div>
{rule('check', GOOD, '<b>Code disposes.</b> A model reasons, code checks (<code>verify_case</code>, <code>verify_plan</code>, <code>verify_desk</code>); a scripted team passes every scenario with no network.')}
{rule('eye', INK, '<b>Nothing is silent.</b> A held action, a doubted value, an unknown alarm, a model outage: each is a named event.')}
</div></div>
<h2>The six departments</h2>
<table><tr><th>Team</th><th>Incident types</th><th>Acts through</th><th>Reasoning</th></tr>
<tr><td>Police</td><td>crime</td><td>dispatch (pursuit, contain), alert, recall</td><td>Analyst, Tactician, Chief</td></tr>
<tr><td>Fire</td><td>fire</td><td>dispatch fire unit, alert</td><td>desk: Analyst, Chief</td></tr>
<tr><td>Ambulance and medical</td><td>accident</td><td>dispatch ambulance, alert</td><td>desk</td></tr>
<tr><td>Traffic control</td><td>jam</td><td>hold a signal green</td><td>desk</td></tr>
<tr><td>Disaster response</td><td>flood</td><td>alert, close a valve (a person approves)</td><td>desk</td></tr>
<tr><td>Utilities</td><td>overload, smog</td><td>alert, cut a zone (a person approves)</td><td>desk</td></tr></table>
<p>A department is three files (a manifest of detectors and actuators, reflex rules, a playbook), so a new kind of incident is a new pack, not new code. A desk can only advise neighbouring zones; it picks zone ids and never words.</p>
"""))
    p.append(page(6, "Part 2 · 2.1 Incident detection", f"""
<h1>2.1 Incident detection: five stages, each able to stop or flag</h1>
<p class='lede'>A reading becomes an incident only after it has been checked, believed, compared with what was expected, and matched to a department. At each stage something specific can go wrong, and the Brain says so instead of acting or staying silent.</p>
{fig_detection()}
<p class='cap'>Figure 4. The detection pipeline with one scenario for each thing a stage can stop. The scenarios are in the Test Book and reproduce from one command.</p>
<div class='cols'><div>
<h3>Prediction is part of detection</h3>
<p>Each sensor learns its own normal (running mean and spread, taught only by trusted readings). A reading many spreads away is a <i>surprise</i>; the first is <i>doubted</i> and the reflex that would act on it is held until another reading agrees. Two sensors that should move together are watched through their <i>difference</i>, so a slow creep one of them makes is caught.</p>
<p>The same machinery looks ahead: a level tracker forecasts when a river reaches the flood line, which triggers an early public alert and raises the incident's attention. That alert is not sent on a doubted or disputed gauge.</p>
</div><div>
<h3>Three things the Brain says instead of staying silent</h3>
<p><b>Unknown alarm.</b> A trusted camera anomaly that is neither a crime nor a collision, or a call in the category &lsquo;other&rsquo;, opens no incident; <code>brain.human.needed</code> says a person may be needed.</p>
<p><b>No procedure.</b> A desk whose playbook has nothing for the incident type first reads the department&rsquo;s other procedures; with none it sends nothing and asks for a person.</p>
<p><b>Stalled incident.</b> An open incident with no new evidence for <code>triage.stall_s</code> asks for a person. The screen shows a red bar for each.</p>
</div></div>
<table><tr><th>What can stop a reading</th><th>Event</th><th>Shown by</th></tr>
<tr><td>bad signature, replay, out-of-range value</td><td><code>brain.reading.rejected</code> with a stable code</td><td>Table 2, redteam</td></tr>
<tr><td>untrusted evidence</td><td><code>brain.action.blocked</code> (trust)</td><td>t13, t15</td></tr>
<tr><td>a jump the sensor&rsquo;s own history cannot explain</td><td><code>brain.percept.surprise</code> (doubted)</td><td>forward-bench</td></tr>
<tr><td>a sensor goes silent</td><td>nothing opens; the other sources carry on</td><td>t15</td></tr></table>
"""))
    p.append(page(7, "Part 2 · 2.2 Decision method", f"""
<h1>2.2 Decision method: rules, agents and solvers, joined</h1>
<p class='lede'>The Brain does not use one method, it uses three and connects them. <b>Rules</b> answer at once. <b>Agent teams</b> (a model in each role, or a scripted stand-in) weigh the case. <b>Solvers</b> compute what judgement should not guess: which station, how few units, which cut, when the water arrives. The solvers run in code and their answers are written into the team&rsquo;s brief, so a model that never calls a tool still reads them.</p>
{fig_decision()}
<p class='cap'>Figure 5. The decision pipeline. The reflex tier and the team tier run side by side; both end at the same gate.</p>
{fig_matrix()}
<p class='cap'>Figure 6. Which tool serves which team. The solvers are on by default; each carries a certificate (status, objective, bound, hash of its inputs). A solver that fails leaves the old behaviour in place and says so.</p>
"""))
    p.append(page(8, "Part 2 · 2.3 How it picks an actuator", f"""
<h1>2.3 How the Brain picks an actuator, and why a call can still be refused</h1>
<p class='lede'>An actuator is chosen in three steps: the incident type decides which department may act and with what; the station or device is chosen (nearest, or the solver&rsquo;s choice when incidents compete); and the gate decides whether the call may go. The Brain never calls the Twin directly.</p>
<div class='cols'><div>
<h3>Which actuator</h3>
<table><tr><th>Incident</th><th>Actuator</th></tr>
<tr><td>crime</td><td><code>dispatch_unit</code> police (pursuit, contain), <code>broadcast_alert</code>, <code>recall_unit</code></td></tr>
<tr><td>fire, accident</td><td><code>dispatch_unit</code> fire or ambulance</td></tr>
<tr><td>jam, ambulance route</td><td><code>set_signal_phase</code> green</td></tr>
<tr><td>flood</td><td><code>broadcast_alert</code>, <code>set_valve_state</code></td></tr>
<tr><td>overload</td><td><code>broadcast_alert</code>, <code>set_grid_connection</code></td></tr></table></div><div>
<h3>Which station or device</h3>
<p>Nearest by hop distance, excluding quarantined and reserved stations. When two or more incidents want the same kind of unit, the dispatch solver solves them together and its choice is used <i>only if it saves cost</i>: for two collisions the far ambulance goes to the first so the close one is free for the second (cost 2.8 against 4.2, checked against brute force by <code>brain optimise-bench</code>). With one incident the solver is not consulted at all.</p>
<p>A cascade analysis weighs what each cut would darken (a hospital counts 10), and the shed solver picks the cheapest set that removes the excess.</p></div></div>
{fig_gate()}
<p class='cap'>Figure 7. The gate. Every proposal from a rule, an agent or a solver meets the same eleven checks in order; a failed check is an event with its reason. A call the Twin never answered frees its key, so it can be retried; a Twin that did act answers <code>duplicate</code>.</p>
<p>The result of each call returns as a timeline event; a dispatched unit&rsquo;s later <code>unit_status</code> readings close the incident, and an arrest or a stand-down recalls every unit still out.</p>
"""))
    p.append(page(9, "Part 2 · 2.4 Interconnection in action", f"""
<h1>2.4 The interconnection in action</h1>
<p class='lede'>The value of the design shows where several parts meet. Each column is a real scenario or a real failure, and each step is a different component handing its result to the next.</p>
{fig_flows()}
<p class='cap'>Figure 8. Three flows. Left: the solver, the corridor planner, the desk and the explanation all meet on one decision. Middle: a forecast, the gate, the triage and a desk meet on one river. Right: the model-health monitor, the teams and the screen meet on a failure.</p>
<div class='cols'><div>
<h3>Learning closes the loop</h3>
<p>A closed incident is kept as an episode. <code>brain sleep</code> finds a plan the team made the same way more than once, rehearses it as a candidate reflex against the real team, and promotes it only if it passes every check. The promoted rule is a <i>cache of a verified deliberation</i>: it never reads whether a dispatch worked. The Academy tunes thirteen listed parameters one step at a time on synthetic streams and held-out seeds; the gate, contracts and suspect scoring are not on the list.</p></div><div>
<h3>Explanation is part of the same wiring</h3>
<p>Every decision, held action and incident can be explained: the events behind it, the knowledge it cited, the solver&rsquo;s certificate, and counterfactuals proved by changing one input on the real gate. A signed bundle fails if one fact changes. The log is hash-chained and a run replays from its input journal.</p></div></div>
<table><tr><th>Evidence that the parts work together</th><th>Result</th></tr>
<tr><td>Test suite (units, scenarios, API, security)</td><td>1,064 passed</td></tr>
<tr><td>Test Book, every scenario, frozen decisions</td><td>4 scenarios, no differences from the frozen baseline</td></tr>
<tr><td>Held-out variants (shifted, reseeded, decoyed)</td><td>50 of 50 decide as their base</td></tr>
<tr><td>Red team (forged and replayed readings, wrong scopes, floods)</td><td>24 attacks, all refused</td></tr>
<tr><td>Learning curve on t14</td><td>team runs 1 to 0; last action 94.7 ms to 35.5 ms; decisions identical</td></tr></table>
"""))
    p.append(page(10, "Part 2 · 2.5 Security and trust", f"""
<h1>2.5 Security: what is trusted, what is not, and what happens when it is wrong</h1>
<p class='lede'>Every input is hostile until it is checked, every model answer is a suggestion, and the only way out is one signed call that a person must approve when it is high-impact. The threats are mapped to MITRE ATT&amp;CK for ICS and Enterprise and to MITRE ATLAS for the AI parts. Each attack below was run against the code (<code>docs/SECURITY-MITRE.md</code>).</p>
<h2>Six trust boundaries and what guards each</h2>
<table style='font-size:7.3pt'><tr><th style='width:17%'>Boundary</th><th style='width:15%'>Trusted?</th><th>Control</th></tr>
<tr><td>Twin to Brain: readings</td><td>No, until checked</td><td>HMAC-SHA256 or Ed25519 over canonical JSON, key ids with expiry, a rising sequence number per sensor, schema and ranges; only allowlisted fields are kept; an optional freshness limit (<code>twin.max_age_s</code>)</td></tr>
<tr><td>Guardian to Brain: verdicts, retractions</td><td>Yes, highly</td><td>Schema check; the gate asks for independent trusted sources by impact level and a person for the highest; only the Guardian&rsquo;s own token may retract a verdict</td></tr>
<tr><td>People and partners to the API</td><td>By scope</td><td>Scoped tokens off loopback (read, analyse, push, approve, admin), short-lived signed tokens that can be revoked, body and rate limits, a partner may push only into its own namespace and <code>brain.*</code> is refused</td></tr>
<tr><td>Brain to the language model</td><td>Output is untrusted</td><td>Ids and fields are limited to safe characters before any prompt; read-only tools; models pick zones, never words; code verifies the answer; then the gate</td></tr>
<tr><td>Brain to Twin: actuator calls</td><td>The Twin must verify</td><td>Eleven gate checks; each call is signed with its time and a one-time number; a valve or the grid needs a signed approval bound to the exact parameters, used once</td></tr>
<tr><td>Brain to its own disk</td><td>Mostly</td><td>Hash-chained log with a signed head; learning only from trusted readings; self-tuning limited to a listed set of numbers, each with a range</td></tr></table>
<h2>Attacks tried, and what happened</h2>
<table style='font-size:7.3pt'><tr><th style='width:21%'>MITRE technique</th><th style='width:41%'>The attack</th><th>Result</th></tr>
<tr><td>ICS T1692.002 forged reading</td><td>Wrong key, no signature, one field edited after signing, the same sequence number twice, an unknown key id, <code>alg: none</code></td><td>Refused every time (A1 to A4, A20 to A22)</td></tr>
<tr><td>ICS T1692.002 delayed reading</td><td>A genuine signed reading held back and delivered late</td><td>Passes by default; refused as stale once <code>twin.max_age_s</code> is set (A24)</td></tr>
<tr><td>ICS T1692.001, T0849 forged call, masquerading</td><td>An approval reused with changed parameters or signed with another secret; the Twin pushes as the Guardian or takes back its verdict</td><td>Refused (A13, A14, A17, A18, A23)</td></tr>
<tr><td>Enterprise T1190, T1078</td><td>No token, a made-up or forged token, a read token doing admin work, 28 path spellings by 7 methods, file-path tricks</td><td>None got through (A8 to A12)</td></tr>
<tr><td>ATLAS AML.T0051, T0053 injection, tool misuse</td><td>An instruction in a sensor id or a hidden value field (30 hostile strings); a tool that tries to actuate</td><td>Refused or dropped before any prompt; no actuator tool can exist (A5 to A7, A19)</td></tr>
<tr><td>ATLAS AML.T0020 poisoning</td><td>Teaching the Brain something false through sleep or tuning</td><td>Sleep learns from trusted readings only and a retraction makes it forget; the folders are off unless set</td></tr>
<tr><td>ICS T0830 in the middle</td><td>An answer to the Guardian URL that says <code>trusted</code> for anything</td><td><b>Gets through today:</b> a verdict is checked for shape, not signed</td></tr></table>
<h2>What is not done</h2>
<div class='cols'><div>
{rule('alert', BAD, '<b>Verdicts are not signed.</b> Fix: the readings&rsquo; key ring, or mutual TLS (<code>guardian.tls</code>, built).')}
{rule('lock', WARN, '<b>No TLS by default.</b> Signatures still protect readings and calls in transit.')}
</div><div>
{rule('eye', WARN, '<b>Freshness limit off.</b> Set it to a few times the live Twin&rsquo;s interval.')}
{rule('plug', MUTED, '<b>Real partners not tried.</b> Their checks of time and one-time numbers are untested.')}
</div></div>
<p class='cap'>Evidence: <code>uv run brain redteam</code> (24 attacks, all refused), <code>brain security-check</code>, <code>scripts/security_poc.py</code> (13 attacks in process), <code>bandit</code> clean, <code>pip-audit</code>, a software bill of materials. Threat list: <code>docs/SECURITY.md</code>; technique by technique: <code>docs/SECURITY-MITRE.md</code>.</p>
"""))
    p.append(page(11, "Part 2 · 2.6 Tech stack  ·  Part 4 · Test Book", f"""
<h1>2.6 Technology stack</h1>
<p class='lede'>Standard, well-known parts, chosen so each one has one job and a named neighbour. The stack runs offline: the embedding model is baked into the image, the screen loads nothing from the internet, and a model outage only changes who reasons.</p>
{fig_stack()}
<p class='cap'>Figure 9. The stack and what each part feeds. Logos identify the technologies; each belongs to its owner and none implies endorsement.</p>
<h1 style='margin-top:4mm'>4. Test Book (the Brain&rsquo;s scenarios)</h1>
<p>Four scenarios, each one trigger (<code>uv run brain scenario dN</code>) and one log in <code>logs/</code>, with expectations in <code>scenarios/</code>. Together they cover the brief&rsquo;s four interaction rows. The generated list is <code>docs/TESTBOOK-brain.md</code>.</p>
<table><tr><th>ID</th><th>Scenario</th><th>Layers</th><th>Expected output</th></tr>
<tr><td>t12</td><td>A calm day</td><td>Twin, Brain</td><td>no incident, no actuator call: the Brain does not overreact</td></tr>
<tr><td>t13</td><td>A fake flood</td><td>Twin, Guardian, Brain</td><td>the gauge is untrusted; the gate refuses the warning and the valve call; nothing reaches the city</td></tr>
<tr><td>t14</td><td>A crime and a pursuit</td><td>Twin, Guardian, Brain</td><td>reflex dispatch, a team perimeter checked and verified, units recalled at the arrest</td></tr>
<tr><td>t15</td><td>A flood, an attack and a layer down</td><td>all three</td><td>warning sent, valve held, forged report sends no police, one &lsquo;Guardian away&rsquo; and low-impact alerts only</td></tr></table>
"""))
    return p


def document(embed_fonts: bool) -> str:
    import re
    faces = ""
    for family, weight, file in (("B612", 400, "B612-Regular.woff2"), ("B612", 700, "B612-Bold.woff2"),
                                 ("B612 Mono", 400, "B612Mono-Regular.woff2"), ("B612 Mono", 700, "B612Mono-Bold.woff2")):
        src = "data:font/woff2;base64," + base64.b64encode((FONTS / file).read_bytes()).decode() if embed_fonts else (FONTS / file).as_uri()
        faces += f"@font-face{{font-family:'{family}';font-weight:{weight};src:url('{src}') format('woff2')}}"
    body = "".join(pages())
    return re.sub(r"\s+\n", "\n", f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>City Brain: report, Parts 0, 2 and 4</title><style>{faces}{CSS}</style></head><body>{body}</body></html>")


def main() -> int:
    browser = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if browser is None:
        print("error: needs Chromium to print the PDF", file=sys.stderr)
        return 1
    PAGE.write_text(document(True), encoding="utf-8")
    with tempfile.TemporaryDirectory() as work:
        src = Path(work) / "report.html"
        src.write_text(document(False), encoding="utf-8")
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--allow-file-access-from-files",
                        f"--user-data-dir={work}/profile", f"--print-to-pdf={PDF}", src.as_uri()], check=True, capture_output=True, timeout=180)
    print(f"wrote {PDF.relative_to(ROOT)} and {PAGE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
