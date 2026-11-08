"""The input journal: every raw input a run received, signed, so the run can be played again."""

import json
import os

import pytest

from brain.baseline import MODELS
from brain.contracts import ActuatorCall, ActuatorResult
from brain.journal import JournalError, JournalingGuardian, JournalingTwin, JournalWriter, read_journal, reading_record
from brain.ports import GuardianUnavailable
from brain.scenario import DEV_SECRETS, inproc_partners, load_scenario, run_scenario

SECRET = "journal-test-secret"


async def run_b2(folder):
    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    folder.mkdir()
    result = await run_scenario(load_scenario("t14"), inproc_partners(), models=MODELS, speed=0, timeout_s=30, log_dir=folder, deterministic=True)
    return result, next(folder.glob("*.inputs.jsonl"))


async def test_every_reading_and_verdict_the_brain_received_is_in_the_journal_in_order(tmp_path):
    result, path = await run_b2(tmp_path / "run")

    journal = read_journal(path)

    received = [e.data["sensor_id"] for e in result.sink.events if e.type in ("brain.reading.received",)]
    journalled = [r["envelope"]["sensor_id"] for r in journal.inputs if r["kind"] == "reading"]
    assert journalled == received and journalled
    assert len(received) == len([r for r in journal.inputs if r["kind"] == "verdict"])


class FakeTwin:
    async def stream_readings(self):
        yield {"sensor_id": "cam-07-02", "sequence_no": 1, "value": {"congestion_score": 0.4, "age": 44}}

    async def call_actuator(self, call):
        return ActuatorResult(status="dispatched", unit_id="unit-p-02")

    async def get_topology(self):
        return {"zones": []}

    async def list_capabilities(self):
        return {"dispatch_unit": "send a unit"}


def test_the_journal_keeps_the_envelope_as_received_except_the_fields_perception_dropped():
    raw = {"sensor_id": "cam-07-02", "sequence_no": 1, "value": {"congestion_score": 0.4, "age": 44},
           "provenance": {"signed_by": "twin", "hmac": "abc"}}

    record = reading_record(raw, dropped=["age"])

    assert record["envelope"]["value"] == {"congestion_score": 0.4}  # demographic fields are gone for good
    assert record["envelope"]["sensor_id"] == "cam-07-02" and record["stripped"] == ["age"]
    assert record["original_hmac"] == "abc"  # the Twin's own signature no longer covers the stripped copy, so it is kept beside it
    assert raw["value"]["age"] == 44  # the input itself is untouched


def test_a_rejected_reading_is_stripped_of_demographic_names_too():
    raw = {"sensor_id": "x", "value": {"gender": "f", "level_m": 1.2}}

    assert reading_record(raw, dropped=[])["envelope"]["value"] == {"level_m": 1.2}


async def test_the_twins_answers_to_calls_and_questions_are_journalled(tmp_path):
    writer = JournalWriter(tmp_path / "j.jsonl", {"run_id": "t"}, SECRET)
    twin = JournalingTwin(FakeTwin(), writer)
    call = ActuatorCall(actuator_id="police-dispatch-05", action="dispatch_unit", params={}, requesting_layer="city_brain",
                        justification="x", trust_ref="verdict-000001")

    await twin.get_topology()
    await twin.list_capabilities()
    await twin.call_actuator(call)
    writer.close()

    kinds = [r["kind"] for r in read_journal(tmp_path / "j.jsonl", SECRET).inputs]
    assert kinds == ["topology", "capabilities", "actuator_result"]


class SilentGuardian:
    async def get_verdict(self, reading, deadline_s):
        raise GuardianUnavailable("no answer")

    async def is_quarantined(self, device_id):
        return False


async def test_a_silent_guardian_is_journalled_as_silent(tmp_path):
    writer = JournalWriter(tmp_path / "j.jsonl", {"run_id": "t"}, SECRET)
    guardian = JournalingGuardian(SilentGuardian(), writer)

    with pytest.raises(GuardianUnavailable):
        await guardian.get_verdict({"sensor_id": "cam-07-02", "sequence_no": 1}, 2.0)
    await guardian.is_quarantined("police-dispatch-05")
    writer.close()

    kinds = [r["kind"] for r in read_journal(tmp_path / "j.jsonl", SECRET).inputs]
    assert kinds == ["verdict_unavailable", "quarantine"]


def test_a_changed_byte_fails_the_chain_with_the_line_number(tmp_path):
    path = tmp_path / "j.jsonl"
    writer = JournalWriter(path, {"run_id": "t"}, SECRET)
    writer.append("reading", envelope={"sensor_id": "a"})
    writer.append("reading", envelope={"sensor_id": "b"})
    writer.close()
    lines = path.read_text().splitlines()
    lines[2] = lines[2].replace('"b"', '"c"')
    path.write_text("\n".join(lines) + "\n")

    with pytest.raises(JournalError, match="line 3"):
        read_journal(path, SECRET)


def test_a_journal_sealed_with_another_secret_is_refused(tmp_path):
    path = tmp_path / "j.jsonl"
    writer = JournalWriter(path, {"run_id": "t"}, SECRET)
    writer.append("reading", envelope={"sensor_id": "a"})
    writer.close()

    with pytest.raises(JournalError, match="seal"):
        read_journal(path, "another-secret")


async def test_the_journal_carries_no_secret(tmp_path):
    _, path = await run_b2(tmp_path / "run")

    text = path.read_text()

    for name in ("TWIN_HMAC_SECRET", "BRAIN_HMAC_SECRET"):
        assert os.environ[name] not in text
    assert "age" not in {key for line in text.splitlines() for key in json.loads(line).get("envelope", {}).get("value", {})}


async def test_the_journal_header_carries_the_environment_fingerprint(tmp_path):
    _, path = await run_b2(tmp_path / "run")

    env = read_journal(path).header["env"]

    assert env["clock"] == "deterministic" and "lock_sha256" in env and "packages" in env
