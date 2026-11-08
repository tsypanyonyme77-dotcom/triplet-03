"""`brain improve`: the bounded self-improvement loop, in one command and one report.

Measure the benchmarks that have ground truth; ask the Academy what it would change (a dry run, inside the declared surface and fence);
verify the whole Brain still decides as recorded, passes the red team and the conformance checks; and only then, with `--apply`, let the Academy
write its overlay. Nothing outside `mind/surface.py` can change, no dispatch outcome is ever a signal, and "no proposal passes" is a valid result.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Improvement:
    measured: dict[str, Any] = field(default_factory=dict)
    proposals: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    applied: bool = False
    note: str = ""


async def improve(
    folder: Path, *, apply: bool, measure: Callable[[], Awaitable[dict[str, Any]]], propose: Callable[[bool], Awaitable[Any]],
    verify: Callable[[], Awaitable[list[Check]]],
) -> Improvement:
    result = Improvement(measured=await measure())
    dry = await propose(True)
    result.proposals, result.rejected = list(dry.promoted), list(dry.rejected)
    result.checks = await verify()
    ok = all(c.passed for c in result.checks)
    if not result.proposals:
        result.note = "no proposal passes the Academy's fence: nothing to apply"
    elif not ok:
        result.note = "a verification failed: nothing is applied, whatever the proposals gain"
    elif not apply:
        result.note = "every verification passes; run again with --apply to write the overlay"
    else:
        await propose(False)
        result.applied, result.note = True, "applied: undo with `brain academy --rollback`"
    return result


def markdown(date: str, r: Improvement) -> str:
    lines = [f"# Improvement run, {date}", "", f"**Outcome:** {r.note}", "", "## Measured before", ""]
    lines += [f"- {k}: {v}" for k, v in r.measured.items()]
    lines += ["", "## Proposed by the Academy (inside the declared surface)", ""]
    lines += [f"- {p['path']}: {p['from']} to {p['to']} (design gain {p['design_gain']}, held-out gain {p['held_out_gain']})" for p in r.proposals] or ["- none"]
    if r.rejected:
        lines += ["", "## Rejected", ""] + [f"- {p.get('path')}: {p.get('reason', '')}" for p in r.rejected]
    lines += ["", "## Verification", ""] + [f"- {'PASS' if c.passed else 'FAIL'} {c.name}: {c.detail}" for c in r.checks]
    return "\n".join(lines) + "\n"
