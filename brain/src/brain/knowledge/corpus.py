"""Reference documents as knowledge: a markdown file cut into chunks along its headings, so one chunk is one retrievable, citable idea."""

from __future__ import annotations

import re
from pathlib import Path

from brain.knowledge import KnowledgeItem

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def _paragraphs(text: str) -> list[tuple[tuple[str, ...], str]]:
    """(heading path, paragraph) in file order. Code blocks are left out: they are examples, not prose to retrieve."""
    path: list[tuple[int, str]] = []
    out: list[tuple[tuple[str, ...], str]] = []
    lines: list[str] = []
    fenced = False

    def flush() -> None:
        paragraph = " ".join(" ".join(lines).split())
        if paragraph:
            out.append((tuple(title for _, title in path), paragraph))
        lines.clear()

    for line in text.splitlines():
        if line.strip().startswith("```"):
            flush()
            fenced = not fenced
        elif fenced:
            continue
        elif heading := _HEADING.match(line):
            flush()
            level = len(heading[1])
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, heading[2]))
        elif not line.strip():
            flush()
        else:
            lines.append(line.strip())
    flush()
    return out


def load_reference(path: Path, *, max_words: int = 160, department: str | None = None) -> list[KnowledgeItem]:
    """Chunks of one document, ids `REF-<NAME>-01`, `-02`, ... A chunk holds paragraphs of one section up to `max_words`; a single
    paragraph longer than that is kept whole rather than cut mid-sentence."""
    chunks: list[tuple[tuple[str, ...], list[str]]] = []
    for headings, paragraph in _paragraphs(path.read_text()):
        words = len(paragraph.split())
        if chunks and chunks[-1][0] == headings and sum(len(p.split()) for p in chunks[-1][1]) + words <= max_words:
            chunks[-1][1].append(paragraph)
        else:
            chunks.append((headings, [paragraph]))
    name = re.sub(r"[^A-Z0-9]+", "-", path.stem.upper()).strip("-")
    return [
        KnowledgeItem(id=f"REF-{name}-{n:02d}", kind="reference", title=" > ".join(headings) or path.stem, text=" ".join(paragraphs),
                      department=department)
        for n, (headings, paragraphs) in enumerate(chunks, 1)
    ]


def reference_items(documents: list[str], home: Path) -> list[KnowledgeItem]:
    """The configured documents that exist; a missing one is skipped, not an error (the Brain must start without its docs)."""
    return [item for name in documents if (home / name).is_file() for item in load_reference(home / name)]
