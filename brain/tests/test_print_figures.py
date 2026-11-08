"""The print-mode figures: standalone, black and white, parseable as XML, and legible at a full landscape page."""

import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

DIAGRAMS = Path(__file__).parents[1] / "docs" / "diagrams"


@pytest.fixture(scope="module")
def figures(tmp_path_factory):
    sys.path.insert(0, str(DIAGRAMS))
    spec = importlib.util.spec_from_file_location("print_figures", DIAGRAMS / "print_figures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out = tmp_path_factory.mktemp("figures")
    return module, out, module.write_all(out, 270.0)


def test_every_figure_the_report_needs_is_written_as_its_own_svg_file(figures):
    module, out, rows = figures

    assert [r["number"] for r in rows if r["number"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert all((out / f"{r['slug']}.svg").exists() for r in rows)


def test_each_file_is_well_formed_xml_with_the_svg_namespace(figures):
    _, out, rows = figures

    for row in rows:
        root = ET.parse(out / f"{row['slug']}.svg").getroot()
        assert root.tag == "{http://www.w3.org/2000/svg}svg", row["slug"]


def test_no_file_depends_on_the_page_around_it_for_its_colours_or_fonts(figures):
    _, out, rows = figures

    for row in rows:
        text = (out / f"{row['slug']}.svg").read_text(encoding="utf-8")
        assert "var(--" not in text and "fonts.googleapis" not in text and "@import" not in text, row["slug"]


def test_a_monochrome_printer_loses_nothing_because_the_drawings_use_only_greys_black_and_white(figures):
    _, out, rows = figures
    style = figures[0].PRINT_CSS

    colours = {c.lower() for c in __import__("re").findall(r"#[0-9a-fA-F]{3,6}\b", style)}
    assert all(len(set(c[1:])) <= 2 and (len(c) == 4 or c[1:3] == c[3:5] == c[5:7]) for c in colours), colours


def test_the_smallest_text_prints_at_seven_points_or_more_on_a_landscape_page(figures):
    module, _, rows = figures

    assert all(r["pt"] >= module.MIN_PT for r in rows), {r["slug"]: round(r["pt"], 1) for r in rows if r["pt"] < module.MIN_PT}


def test_the_figures_table_says_how_each_one_prints(figures):
    _, out, rows = figures
    text = (out / "FIGURES.md").read_text(encoding="utf-8")

    assert all(r["slug"] in text for r in rows) and "pt" in text and "Figure 7" in text


def test_the_gate_is_told_apart_by_a_heavy_line_not_by_colour(figures):
    style = figures[0].PRINT_CSS

    assert ".box.gate" in style and "stroke-width: 3.2" in style
