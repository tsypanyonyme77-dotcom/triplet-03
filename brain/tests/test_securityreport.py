"""The security report: a threat is covered only by evidence that ran and passed."""

from brain.securityreport import assess, markdown, parse

TABLE = """| # | Threat | Defence | Proof |
| --- | --- | --- | --- |
| 1 | A forged reading | HMAC | A1, A2 |
| 2 | A replay | sequence numbers | `tests/test_a.py` |
| 3 | In transit | **Open.** not built | none |
| 4 | Nothing named | something | prose only |
"""


def test_the_table_is_read_into_threats_with_their_tests_and_attacks():
    threats = parse(TABLE)

    assert [t.id for t in threats] == ["1", "2", "3", "4"] and threats[0].attacks == ["1", "2"] and threats[1].tests == ["tests/test_a.py"]


def test_a_threat_with_no_evidence_or_marked_open_is_listed_open_not_covered():
    threats = assess(parse(TABLE), {"tests/test_a.py": True}, {"1": "pass", "2": "pass"})

    assert [t.status for t in threats] == ["pass", "pass", "open", "open"]


def test_the_report_lists_a_failing_test_as_a_failure():
    threats = assess(parse(TABLE), {"tests/test_a.py": False}, {"1": "pass", "2": "fail"})

    assert [t.status for t in threats[:2]] == ["fail", "fail"] and "A2" in threats[0].detail
    assert "FAIL" in markdown("2026-11-05", threats)


def test_the_shipped_threat_table_parses_and_names_only_tests_that_exist():
    from pathlib import Path

    root = Path(__file__).parents[1]
    threats = parse((root / "docs/SECURITY.md").read_text())

    assert len(threats) >= 16 and all((root / f).exists() for t in threats for f in t.tests)
