"""Draw the City Brain architecture and the crime-and-pursuit scenario, and print them to one PDF.

    uv run python docs/diagrams/architecture.py      # writes docs/City-Brain-architecture.pdf

Both diagrams are plain SVG written here by hand, in the timeline screen's typeface and
colours, then printed by headless Chromium so the PDF stays vector and searchable.
"""

from __future__ import annotations

import html
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FONTS = ROOT / "src/brain/api/static/fonts"
OUT = ROOT / "docs/City-Brain-architecture.pdf"

INK, INK2, MUTED, RULE = "#111417", "#3F464A", "#636B6F", "#AEB5AF"
BOARD, BOARD2, STRIP = "#E6E9E4", "#D9DDD7", "#FFFFFF"
BLUE, GOOD, CRITICAL = "#1B49CF", "#18794A", "#C0311E"
SANS, MONO = "B612, sans-serif", "'B612 Mono', monospace"


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def text(x, y, words, size=12, weight=400, fill=INK, anchor="start", family=SANS, rotate=None, halo=False) -> str:
    """`halo` paints a white edge under the letters, so a line passing behind the words does not cut them."""
    turn = f" transform='rotate({rotate} {x} {y})'" if rotate is not None else ""
    edge = f" stroke='{STRIP}' stroke-width='5' stroke-linejoin='round' paint-order='stroke'" if halo else ""
    return (f"<text x='{x}' y='{y}' font-size='{size}' font-weight='{weight}' fill='{fill}' "
            f"text-anchor='{anchor}' font-family=\"{family}\"{turn}{edge}>{esc(words)}</text>")


def rect(x, y, w, h, fill=STRIP, stroke=INK, width=1, radius=6, dash=None) -> str:
    dashed = f" stroke-dasharray='{dash}'" if dash else ""
    return f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='{radius}' fill='{fill}' stroke='{stroke}' stroke-width='{width}'{dashed}/>"


def path(d, color=INK, width=1.25, start=False, end=True, dash=None) -> str:
    marker = "blue" if color == BLUE else "ink"
    ends = (f" marker-start='url(#{marker})'" if start else "") + (f" marker-end='url(#{marker})'" if end else "")
    dashed = f" stroke-dasharray='{dash}'" if dash else ""
    return f"<path d='{d}' fill='none' stroke='{color}' stroke-width='{width}'{dashed}{ends}/>"


def box(x, y, w, h, title, lines=(), sub=None, accent=False, fill=STRIP, mono=(), title_size=14) -> str:
    """A box with a bold name, an optional quiet sub-line and plain lines. `mono` lists lines set in the mono face."""
    parts = [rect(x, y, w, h, fill=fill, stroke=BLUE if accent else INK, width=2 if accent else 1)]
    parts.append(text(x + 12, y + 22, title, size=title_size, weight=700, fill=BLUE if accent else INK))
    line_y = y + 22
    if sub:
        line_y += 17
        parts.append(text(x + 12, line_y, sub, size=11.5, fill=MUTED))
    line_y += 20 if lines else 0
    for line in lines:
        if line:
            parts.append(text(x + 12, line_y, line, size=12, fill=INK2, family=MONO if line in mono else SANS))
        line_y += 16.5
    return "".join(parts)


def svg(width, height, label, body) -> str:
    defs = (
        "<defs>"
        f"<marker id='ink' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'>"
        f"<path d='M0 0L10 5L0 10z' fill='{INK}'/></marker>"
        f"<marker id='blue' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' markerHeight='7' orient='auto-start-reverse'>"
        f"<path d='M0 0L10 5L0 10z' fill='{BLUE}'/></marker>"
        "</defs>"
    )
    return (f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='{esc(label)}' "
            f"xmlns='http://www.w3.org/2000/svg'>{defs}{body}</svg>")


# --------------------------------------------------------------------------- page 1: the system


def system() -> str:
    title = "City Brain architecture: data flows down, and actions leave only through the gate"
    p = [text(24, 36, title, size=20, weight=700),
         text(24, 60, "Everything drawn here is built and runs today. Six departments, five solvers. TSYP14 City Brain layer, updated 6 November 2026.",
              size=12, fill=MUTED)]

    # The two partner layers.
    p.append(box(24, 112, 160, 250, "Twin layer", sub="Cities: Skylines 2",
                 lines=["sends, signed:", "sensor readings", "the city layout", "", "offers actuators:",
                        "dispatch_unit", "broadcast_alert", "recall_unit", "set_signal_phase", "set_valve_state", "set_grid_connection"],
                 mono=("dispatch_unit", "broadcast_alert", "recall_unit", "set_signal_phase", "set_valve_state", "set_grid_connection")))
    p.append(box(930, 184, 150, 136, "Guardian layer",
                 lines=["a trust verdict", "for every reading", "", "a quarantine list", "of actuators"]))

    # The Brain.
    p.append(rect(272, 84, 576, 732, fill=BOARD, stroke=INK, width=2, radius=10))
    p.append(text(288, 106, "City Brain layer", size=14, weight=700))
    left, wide = 288, 544
    p.append(box(left, 118, wide, 50, "1 · Ports and adapters",
                 lines=["Twin over MCP, HTTP or MQTT · Guardian over REST · partner addresses live in config"], title_size=13.5))
    p.append(box(left, 182, wide, 62, "2 · Perception",
                 lines=["Checks contract version, schema, HMAC signature and sequence number",
                        "Drops demographic fields · joins the Guardian's verdict to each reading"]))
    half = (wide - 16) // 2
    p.append(box(left, 258, half, 88, "3 · City Graph",
                 lines=["readings, verdicts, zones, units", "incidents, decisions, actions", "in memory · optional Neo4j"]))
    p.append(box(left + half + 16, 258, half, 88, "Knowledge base",
                 lines=["39 playbook procedures, rules", "vector + keyword search", "local embeddings, offline"]))
    p.append(box(left, 360, wide, 68, "Forward models · level forecast",
                 lines=["each sensor learns its normal and doubts a jump · coupled sensors", "water-level forecast and early alert"], title_size=13.5))

    p.append(rect(left, 442, wide, 200, fill=BOARD2, stroke=INK, width=1, radius=8))
    p.append(text(left + 12, 464, "4 · Six departments: Police, Fire, Ambulance, Traffic, Disaster, Utilities", size=14, weight=700))
    inner = left + 16
    p.append(box(inner, 476, 112, 104, "Triage", lines=["opens an incident", "per detector", "names unknown", "alarms"]))
    p.append(box(inner + 128, 476, 184, 104, "Reflex tier", sub="milliseconds, no LLM",
                 lines=["trust-weighted score", "rules for every team", "LangGraph flow"]))
    p.append(box(inner + 328, 476, 184, 104, "Teams", sub="seconds, in background",
                 lines=["Police: Analyst, Tactician,", "Chief · five desks of two", "Groq LLM or scripted"]))
    p.append(rect(inner, 590, wide - 32, 40, fill=STRIP, stroke=BLUE, width=1))
    p.append(text(inner + 12, 607, "Solvers with certificates, in the team's brief: dispatch · perimeter ·", size=12, fill=INK2))
    p.append(text(inner + 12, 622, "load shedding · level forecast · emergency corridor (the gate still decides)", size=12, fill=INK2))

    p.append(box(left, 656, wide, 66, "5 · Actuation gate: the only path to an actuator", accent=True, fill="#EEF2FC",
                 lines=["schema · capability · allowlist · open incident · trust_ref · evidence · human approval",
                        "no duplicates · cooling · quarantine · budget  →  HMAC-signed call to the Twin"]))
    p.append(box(left, 736, wide, 66, "6 · Timeline and memory",
                 lines=["every step is a CloudEvent: Strip Board and canopy, hash-chained audit log, explanations",
                        "episodes, sleep, Academy · model health and 'a person may be needed' alerts"]))

    # Flow inside the Brain.
    knowledge = left + half + 16 + half // 2
    for x, y0, y1 in ((560, 168, 182), (420, 244, 258), (knowledge, 244, 258), (420, 346, 360), (knowledge, 346, 360), (560, 428, 442),
                      (inner + 128 + 92, 642, 656), (inner + 328 + 92, 642, 656), (560, 722, 736)):
        p.append(path(f"M{x} {y0}V{y1 - 1}"))
    p.append(path(f"M{inner + 112} 528H{inner + 127}"))
    p.append(path(f"M{inner + 312} 528H{inner + 327}"))

    # To and from the partners.
    p.append(path("M184 143H287"))
    p.append(text(236, 135, "readings", size=11.5, fill=INK2, anchor="middle"))
    p.append(path("M288 689H228V362H185", color=BLUE, width=1.75))
    p.append(text(218, 560, "signed actuator calls", size=11.5, fill=BLUE, anchor="middle", rotate=-90))
    p.append(path("M833 217H929", start=True))
    p.append(text(881, 209, "verdict", size=11.5, fill=INK2, anchor="middle"))
    p.append(path("M833 689H890V290H929", start=True))
    p.append(text(904, 500, "quarantined?", size=11.5, fill=INK2, anchor="middle", rotate=-90))
    return svg(1100, 836, title, "".join(p))


# --------------------------------------------------------------------------- page 2: the scenario


LANES = {"twin": 150, "guardian": 310, "perception": 480, "reflex": 650, "team": 820, "gate": 990}


def scenario() -> str:
    title = "The pursuit leaves 6 ms after the deciding reading; the agents add the rest 0.1 s later"
    p = [text(24, 36, title, size=20, weight=700),
         text(24, 60, "Scenario t14, a crime and a pursuit, run in process on 7 November 2026 against the stand-in Twin and Guardian. Times are from its log.",
              size=12, fill=MUTED)]

    heads = {"twin": ("Twin", "Cities: Skylines 2"), "guardian": ("Guardian", "trust layer"),
             "perception": ("Perception", "City Graph, triage"), "reflex": ("Reflex tier", "rules, milliseconds"),
             "team": ("Department team", "agents, seconds"), "gate": ("Actuation gate", "the only way out")}
    p.append(path(f"M{LANES['perception'] - 68} 86H{LANES['gate'] + 68}", end=False, color=INK2))
    p.append(text((LANES["perception"] + LANES["gate"]) / 2, 80, "City Brain", size=12.5, weight=700, fill=INK2, anchor="middle"))
    bottom = 812
    for key, x in LANES.items():
        name, sub = heads[key]
        accent = key == "gate"
        p.append(rect(x - 70, 94, 140, 46, fill="#EEF2FC" if accent else STRIP, stroke=BLUE if accent else INK, width=2 if accent else 1))
        p.append(text(x, 113, name, size=13.5, weight=700, fill=BLUE if accent else INK, anchor="middle"))
        p.append(text(x, 130, sub, size=11, fill=MUTED, anchor="middle"))
        p.append(path(f"M{x} 140V{bottom}", color=RULE, width=1, end=False, dash="4 4"))

    def arrow(y, a, b, label, accent=False, back=False, both=False, note=None):
        xa, xb = LANES[a], LANES[b]
        sign = 1 if xb > xa else -1
        color = BLUE if accent else INK
        p.append(path(f"M{xa + sign * 3} {y}H{xb - sign * 4}", color=color, width=1.75 if accent else 1.25,
                      start=both, dash="5 4" if back else None))
        p.append(text((xa + xb) / 2, y - 6, label, size=12, weight=700 if accent else 400, fill=color, anchor="middle", halo=True))
        if note:
            p.append(text((xa + xb) / 2, y + 15, note, size=11, fill=MUTED, anchor="middle", halo=True))

    def step(y, number):
        p.append(f"<circle cx='40' cy='{y - 4}' r='11' fill='{INK}'/>")
        p.append(text(40, y, str(number), size=12, weight=700, fill=STRIP, anchor="middle"))

    def mark(y, lane, lines, width=200):
        x = LANES[lane]
        h = 10 + 15 * len(lines)
        p.append(rect(x - width / 2, y, width, h, fill=BOARD, stroke=INK2, width=1, radius=5))
        for i, line in enumerate(lines):
            p.append(text(x, y + 17 + 15 * i, line, size=11.5, fill=INK, anchor="middle"))

    y = 176
    step(y, 1); arrow(y, "twin", "perception", "sightings near the scene, all trusted")
    y += 46
    step(y, 2); arrow(y, "twin", "perception", "camera: robbery in Downtown (0.93)")
    y += 26; arrow(y, "perception", "guardian", "verdict?")
    y += 22; arrow(y, "guardian", "perception", "trusted", back=True)
    y += 10; mark(y, "perception", ["incident inc-0001 opened"], width=190)
    y += 56
    step(y, 3); arrow(y, "twin", "perception", "cit-88213 running 18 km/h (trusted)")
    y += 26; arrow(y, "perception", "reflex", "score everyone")
    y += 10; mark(y, "reflex", ["score 0.82: at the scene and fled,", "nobody else fled → suspect"], width=230)
    y += 64
    step(y, 4); arrow(y, "reflex", "gate", "pursue cit-88213 (rule POL-001)")
    y += 26; arrow(y, "gate", "guardian", "is this actuator quarantined?", both=True)
    y += 30; arrow(y, "gate", "twin", "dispatch_unit · pursuit · trust_ref · signed", accent=True,
                   note="6 ms after the reading in step 3")
    y += 52
    step(y, 5); arrow(y, "reflex", "team", "ask for a plan")
    y += 10; mark(y, "team", ["Analyst → Tactician", "→ Chief → verifier"], width=170)
    y += 58; arrow(y, "team", "gate", "intercept + alert")
    y += 28; arrow(y, "gate", "twin", "dispatch_unit · contain  +  broadcast_alert", accent=True,
                   note="0.1 s later with the scripted team · about 5.5 s with Groq agents (an earlier run)")
    y += 52
    step(y, 6); arrow(y, "twin", "perception", "unit_status … apprehended (trusted)")
    y += 10; mark(y, "perception", ["incident inc-0001 closed"], width=190)
    y += 56
    step(y, 7); arrow(y, "reflex", "gate", "stand down (rule POL-003)")
    y += 28; arrow(y, "gate", "twin", "recall_unit for every unit still out", accent=True,
                   note="3 ms after the arrest report")

    foot = bottom + 18
    p.append(rect(24, foot, 1052, 52, fill=BOARD, stroke=RULE, width=1, radius=6))
    p.append(text(40, foot + 21, "Every arrow is also a timeline event: it appears on the Strip Board screen and in the hash-chained audit log.",
                  size=12, fill=INK2))
    p.append(text(40, foot + 39, "If the Guardian answers untrusted in step 2 or 3, nothing is dispatched and the reading is held at the gate with its reason (shown for a flood in scenario t13).",
                  size=12, fill=INK2))
    return svg(1100, foot + 66, title, "".join(p))


# --------------------------------------------------------------------------- printing


def page(body: str) -> str:
    return f"<section class='page'>{body}</section>"


def document() -> str:
    faces = "".join(
        f"@font-face{{font-family:'{family}';font-weight:{weight};src:url('{(FONTS / file).as_uri()}') format('woff2')}}"
        for family, weight, file in (("B612", 400, "B612-Regular.woff2"), ("B612", 700, "B612-Bold.woff2"),
                                     ("B612 Mono", 400, "B612Mono-Regular.woff2"), ("B612 Mono", 700, "B612Mono-Bold.woff2"))
    )
    style = (faces + "@page{size:A4 landscape;margin:9mm}"
             "html,body{margin:0;background:#fff}"
             ".page{width:279mm;height:191mm;display:flex;align-items:center;justify-content:center;break-after:page}"
             ".page:last-child{break-after:auto}svg{width:100%;height:100%}")
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>City Brain architecture</title>"
            f"<style>{style}</style></head><body>{page(system())}{page(scenario())}</body></html>")


def main() -> int:
    browser = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if browser is None:
        print("error: needs Chromium to print the PDF", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as work:  # the page points at this machine's font files, so it is not kept
        source = Path(work) / "architecture.html"
        source.write_text(document(), encoding="utf-8")
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--allow-file-access-from-files",
                        f"--user-data-dir={work}/profile", f"--print-to-pdf={OUT}", source.as_uri()],
                       check=True, capture_output=True, timeout=120)
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
