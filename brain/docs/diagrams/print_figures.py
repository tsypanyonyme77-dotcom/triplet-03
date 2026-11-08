"""The report's figures as standalone black-on-white SVG files, and an A4 landscape PDF of them.

    uv run python docs/diagrams/print_figures.py                 # docs/diagrams/print/*.svg and docs/diagrams/print/FIGURES.md
    uv run python docs/diagrams/print_figures.py --pdf           # also docs/City-Brain-architecture-v2.pdf (needs Chrome, Edge or Chromium)
    uv run python docs/diagrams/print_figures.py --width-mm 160  # check legibility for another printed width

The screen versions in docs/expanded-architecture.html take their colours from CSS variables and need the page around them. These carry
their own style sheet, use no colour a monochrome printer would lose (fills are greys, the gate is a heavy double line, the path out of the
gate is dashed), name no web font, and embed their logos in grey. The drawings are the same code as the screen's, so a structural change is
one redraw: run this again after `expanded_architecture.py`.

The figures are dense on purpose. FIGURES.md says, for each, how large its smallest text prints at the width asked for (default A4 landscape,
270 mm), and flags anything under 7 pt, so a figure that will not read in the report is known before the report is printed.
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import architecture as arch  # noqa: E402  the hand-drawn system and scenario pages (already print colours)
import expanded_architecture as screen  # noqa: E402
from brain_map import side_view  # noqa: E402
from logo_architecture import memory  # noqa: E402

ROOT = HERE.parent.parent
OUT_DIR = HERE / "print"
PDF = ROOT / "docs/City-Brain-architecture-v2.pdf"
MIN_PT = 7.0

# class names the drawings use, and the size each is drawn at (px in the drawing's own units)
CLASS_PX = {"t": 15.0, "s": 12.5, "k": 12.0, "an": 12.0}

PRINT_CSS = """
svg { font-family: Arial, Helvetica, sans-serif; }
.box, .card { fill: #fff; stroke: #000; stroke-width: 1.4; }
.box.new, .card.new { fill: #e3e3e3; }
.box.partner, .card.partner { fill: #fff; stroke-dasharray: 6 4; }
.box.gate, .card.gate { fill: #fff; stroke-width: 3.2; }
.frame { fill: none; stroke: #777; stroke-width: 1.2; }
.tile { fill: #fff; stroke: #999; stroke-width: 1; }
.arrow { fill: none; stroke: #000; stroke-width: 1.6; }
.arrow.ember { stroke-dasharray: 7 4; stroke-width: 2.2; }
.headfill, .headember { fill: #000; }
.t { font: 700 15px Arial, Helvetica, sans-serif; fill: #000; }
.s { font: 400 12.5px Arial, Helvetica, sans-serif; fill: #222; }
.k { font: 400 12px "Courier New", monospace; fill: #333; letter-spacing: .04em; }
.an { font: 400 12px Arial, Helvetica, sans-serif; fill: #333; text-transform: uppercase; letter-spacing: .06em; }
.cortex { fill: #f1f1f1; stroke: #000; stroke-width: 1.4; }
.cbl { fill: #f1f1f1; stroke: #000; stroke-width: 1.2; stroke-dasharray: 3 4; }
.stem { fill: #f1f1f1; stroke: #000; stroke-width: 1.2; }
.wire { fill: none; stroke: #444; stroke-width: 1.5; }
.wire.out { stroke: #000; stroke-width: 2.4; stroke-dasharray: 7 4; }
.tipfill { fill: #000; }
.dot { fill: #555; stroke: #000; stroke-width: 1; }
.dot.gate { fill: #000; }
.dot.agent { fill: #fff; stroke-width: 2.4; }
.dot.twin { fill: #fff; stroke-dasharray: 3 2; }
image { filter: grayscale(1) contrast(1.1); }
"""

# (slug, number in the report or None, title, builder, one sentence for the caption)
FIGURES = [
    ("fig0-context", None, "The City Brain between its partners", screen.context, "The Brain between the Twin and the Guardian, with the protocol on every link."),
    ("fig1-layered-architecture", 1, "The layered architecture", screen.layers, "Six planes from the interoperability edge to learning, the shared spine and the platform. A grey box is new in the Convergence design."),
    ("fig2-planning-graph", 2, "The planning graph", screen.planner, "Solve and deliberate in parallel, reconcile, pause for a person, then the gate. Checkpoints sit under the graph."),
    ("fig3-memory-plane", 3, "The memory plane", memory, "Five stores, each answering a different question, none on the decision path's critical wait."),
    ("fig4-deployment-compose", 4, "Deployment with Docker Compose", screen.deployment, "The Brain, its stand-in partners, stores and observability in one Compose project."),
    ("fig5-scenario-trace", 5, "One scenario traced end to end", arch.scenario, "Scenario t14 across the three layers, with times from its log. (A trace of t15 is not drawn.)"),
    ("fig6-improvement-loop", 6, "The improvement loop", screen.loop, "Observe, measure, propose, verify, promote, audit: bounded, reversible, never on the gate."),
    ("fig7-glass-brain", 7, "The glass brain from the side", side_view, "Each region where the screen draws it. The Brain is brain-inspired: it models functions, not a brain."),
    ("fig8-partner-boundary", 8, "Where logic ends and partners begin", screen.boundary, "Two ports, the adapters outside them, and the configuration file, Interface Card and conformance kit that make a new partner a small change."),
]


def standalone(markup: str, title: str) -> str:
    """One drawing as a file that stands on its own: namespace, title, print style sheet, white background."""
    if "xmlns=" not in markup.split(">", 1)[0]:
        markup = markup.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    background = '<rect width="100%" height="100%" fill="#fff"/>'
    head, _, rest = markup.partition(">")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{head}><title>{html.escape(title)}</title><style>{PRINT_CSS}</style>{background}{rest}\n'


def smallest_text_px(markup: str) -> float:
    """The smallest text in a drawing, in the drawing's own units: classes it uses, inline sizes and size attributes."""
    sizes = [CLASS_PX[c] for c in set(re.findall(r'class="([a-z]+)[" ]', markup)) if c in CLASS_PX and f'class="{c}' in markup]
    sizes += [float(s) for s in re.findall(r"font-size[:=]\s*[\"']?(\d+(?:\.\d+)?)", markup)]
    return min(sizes) if sizes else 12.0


def drawing_width(markup: str) -> float:
    return float(re.search(r'viewBox=["\']0 0 (\d+(?:\.\d+)?) ', markup).group(1))


def printed_pt(markup: str, width_mm: float) -> float:
    return smallest_text_px(markup) * (width_mm / drawing_width(markup)) / 25.4 * 72


def write_all(out_dir: Path, width_mm: float) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for slug, number, title, build, caption in FIGURES:
        markup = build()
        (out_dir / f"{slug}.svg").write_text(standalone(markup, title), encoding="utf-8", newline="\n")
        rows.append({"slug": slug, "number": number, "title": title, "caption": caption, "markup": markup,
                     "pt": printed_pt(markup, width_mm), "pt_column": printed_pt(markup, 160)})
    lines = [f"# Figures for the report\n\nGenerated by `docs/diagrams/print_figures.py`. Smallest text, printed at {width_mm:g} mm wide (A4 landscape) and at 160 mm (a portrait column).\n",
             "| Figure | File | Smallest text at width | At 160 mm | Caption |", "| --- | --- | --- | --- | --- |"]
    for row in rows:
        label = f"Figure {row['number']}" if row["number"] else "(context)"
        flag = "" if row["pt"] >= MIN_PT else " **too small**"
        lines.append(f"| {label}: {row['title']} | `{row['slug']}.svg` | {row['pt']:.1f} pt{flag} | {row['pt_column']:.1f} pt | {row['caption']} |")
    lines.append(f"\nText under {MIN_PT:g} pt is flagged. A figure set across a 160 mm column prints its text near {min(r['pt_column'] for r in rows):.0f} to "
                 f"{max(r['pt_column'] for r in rows):.0f} pt: use these as full-page landscape figures, or redraw one with fewer, larger boxes for the column.")
    (out_dir / "FIGURES.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return rows


def find_browser() -> str | None:
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome", "msedge"):
        if found := shutil.which(name):
            return found
    for path in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(path).exists():
            return path
    return None


def pdf_document(rows: list[dict]) -> str:
    faces = "".join(
        f"@font-face{{font-family:'{family}';font-weight:{weight};src:url('{(arch.FONTS / file).as_uri()}') format('woff2')}}"
        for family, weight, file in (("B612", 400, "B612-Regular.woff2"), ("B612", 700, "B612-Bold.woff2"),
                                     ("B612 Mono", 400, "B612Mono-Regular.woff2"), ("B612 Mono", 700, "B612Mono-Bold.woff2")))
    style = (faces + "@page{size:A4 landscape;margin:9mm}html,body{margin:0;background:#fff}"
             ".page{width:279mm;height:191mm;display:flex;flex-direction:column;align-items:center;justify-content:center;break-after:page}"
             ".page:last-child{break-after:auto}.page svg{width:100%;flex:1;min-height:0}"
             "h2{font:700 13pt Arial,sans-serif;margin:0 0 3mm;align-self:flex-start}p.cap{font:10pt Arial,sans-serif;margin:3mm 0 0;align-self:flex-start;color:#222}" + PRINT_CSS)
    pages = [arch.page(arch.system()), arch.page(arch.scenario())]
    for row in rows:
        if row["slug"] == "fig5-scenario-trace":
            continue  # the scenario page above is the same drawing
        label = f"Figure {row['number']}. " if row["number"] else ""
        pages.append(f"<section class='page'><h2>{html.escape(label + row['title'])}</h2>{row['markup']}<p class='cap'>{html.escape(row['caption'])}</p></section>")
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>City Brain figures</title><style>{style}</style></head><body>{''.join(pages)}</body></html>"


def write_pdf(rows: list[dict]) -> int:
    browser = find_browser()
    if browser is None:
        print("error: needs Chrome, Edge or Chromium to print the PDF", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as work:
        source = Path(work) / "figures.html"
        source.write_text(pdf_document(rows), encoding="utf-8")
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--allow-file-access-from-files",
                        f"--user-data-dir={work}/profile", f"--print-to-pdf={PDF}", source.as_uri()], check=True, capture_output=True, timeout=180)
    print(f"wrote {PDF.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Write the report's figures as print-ready SVG files")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--width-mm", type=float, default=270.0, help="the printed width to check legibility at")
    parser.add_argument("--pdf", action="store_true", help="also print docs/City-Brain-architecture-v2.pdf")
    args = parser.parse_args()
    rows = write_all(args.out, args.width_mm)
    for row in rows:
        print(f"{row['slug']:<30} smallest text {row['pt']:.1f} pt at {args.width_mm:g} mm" + ("" if row["pt"] >= MIN_PT else "   <- under 7 pt"))
    print(f"wrote {len(rows)} figures to {args.out}")
    return write_pdf(rows) if args.pdf else 0


if __name__ == "__main__":
    sys.exit(main())
