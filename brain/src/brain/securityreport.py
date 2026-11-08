"""`brain security-report`: every threat in docs/SECURITY.md with the evidence that runs today.

The table is the maintained list of threats. For each row this runs the tests it names (`tests/test_*.py`) and the red-team attacks it names (`A12`),
and reports the row as passing, failing, or open (no evidence, or the row says so). A threat is never reported as covered by a test that was not run.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROW = re.compile(r"^\|\s*(\w+)\s*\|(.+)\|(.+)\|(.+)\|\s*$")


@dataclass
class Threat:
    id: str
    threat: str
    defence: str
    proof: str
    tests: list[str] = field(default_factory=list)
    attacks: list[str] = field(default_factory=list)
    status: str = "open"
    detail: str = ""


def parse(markdown: str) -> list[Threat]:
    found = []
    for line in markdown.splitlines():
        match = ROW.match(line)
        if not match or match.group(1) in ("#", "---") or set(match.group(1)) <= {"-"}:
            continue
        threat = Threat(match.group(1), match.group(2).strip(), match.group(3).strip(), match.group(4).strip())
        threat.tests = sorted(set(re.findall(r"tests/test_\w+\.py", threat.proof)))
        threat.attacks = sorted(set(re.findall(r"\bA(\d+)\b", threat.proof)), key=int)
        if "brain security-check" in threat.proof:
            threat.tests = sorted(set(threat.tests) | {"tests/test_security_invariants.py"})
        found.append(threat)
    return found


def run_tests(files: list[str], root: Path) -> dict[str, bool]:
    """Each file on its own, so one failure is attributed to the right threat."""
    results = {}
    for file in files:
        done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", file], cwd=root, capture_output=True, check=False)
        results[file] = done.returncode == 0
    return results


def assess(threats: list[Threat], tests: dict[str, bool], attacks: dict[str, str]) -> list[Threat]:
    for t in threats:
        if "**Open" in t.defence or "**Open" in t.proof or not (t.tests or t.attacks):
            t.status, t.detail = "open", "no evidence is run for this threat" if not (t.tests or t.attacks) else "marked open"
            continue
        failing = [f for f in t.tests if not tests.get(f, False)] + [f"A{a}" for a in t.attacks if attacks.get(a) != "pass"]
        t.status, t.detail = ("fail", "failing: " + ", ".join(failing)) if failing else ("pass", f"{len(t.tests)} test files, {len(t.attacks)} attacks")
    return threats


def markdown(date: str, threats: list[Threat]) -> str:
    counts = {s: sum(1 for t in threats if t.status == s) for s in ("pass", "fail", "open")}
    lines = [f"# Security report, {date}", "", f"{counts['pass']} threats with passing evidence, {counts['fail']} failing, {counts['open']} open.", "",
             "| # | Threat | Status | Evidence |", "| --- | --- | --- | --- |"]
    lines += [f"| {t.id} | {t.threat} | {t.status.upper()} | {t.detail} |" for t in threats]
    return "\n".join(lines) + "\n"
