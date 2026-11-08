"""A signed chain head: rewriting a whole log consistently still fails, because only the Brain's key can sign the new tip."""

import json
from datetime import UTC, datetime

from brain.contracts import TimelineEvent
from brain.timeline import GENESIS, JsonlSink, head_path, verify_chain, verify_head

SECRET = "head-test-secret"


def write(path, count=3, monkeypatch=None):
    sink = JsonlSink(path)
    for n in range(count):
        sink.write(TimelineEvent(type="brain.test", subject=f"s{n}", data={"n": n}, time=datetime(2026, 11, 5, 10, 0, n, tzinfo=UTC)))
    sink.close()


def test_a_closed_log_has_a_signed_head_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_HMAC_SECRET", SECRET)
    log = tmp_path / "a.jsonl"
    write(log)

    assert head_path(log).exists() and verify_head(log, SECRET)[0] == "ok"


def test_rewriting_the_whole_chain_consistently_fails_the_head_signature(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_HMAC_SECRET", SECRET)
    log = tmp_path / "a.jsonl"
    write(log)
    head = head_path(log).read_text()
    # an attacker with disk access rewrites the log with a different event and a perfectly valid chain
    forged = tmp_path / "forged.jsonl"
    monkeypatch.delenv("BRAIN_HMAC_SECRET")
    write(forged)
    lines = [json.loads(line) for line in forged.read_text().splitlines()]
    sink = JsonlSink(log)
    sink.write(TimelineEvent(type="brain.test", subject="s0", data={"n": 999}, time=datetime(2026, 11, 5, 10, 0, 0, tzinfo=UTC)))
    sink.close()
    head_path(log).write_text(head)  # the old head, which the attacker cannot re-sign

    assert verify_chain(log)[0] and len(lines) == 3
    assert verify_head(log, SECRET)[0] == "mismatch"
    head_path(log).write_text(head.replace("\"hash\": \"", "\"hash\": \"0"))
    assert verify_head(log, SECRET)[0] == "invalid"


def test_verify_reports_a_missing_head_for_an_old_log_without_failing_it(tmp_path, monkeypatch):
    monkeypatch.delenv("BRAIN_HMAC_SECRET", raising=False)
    log = tmp_path / "old.jsonl"
    write(log)

    assert verify_head(log, SECRET)[0] == "missing" and verify_chain(log)[0] and GENESIS
