"""The clock and the id source: real by default, repeatable when a run asks for it."""

from datetime import UTC, datetime, timedelta

from brain import clock
from brain.baseline import MODELS
from brain.scenario import DEV_SECRETS, inproc_partners, load_scenario, run_scenario

EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def test_the_system_clock_is_the_default_and_moves():
    assert isinstance(clock.current(), clock.SystemClock)

    first, second = clock.current().now(), clock.current().now()

    assert abs((datetime.now(UTC) - first).total_seconds()) < 5
    assert second >= first
    assert clock.current().new_id("evt") != clock.current().new_id("evt")


def test_a_deterministic_clock_returns_the_epoch_plus_the_scenario_offset():
    fixed = clock.DeterministicClock(EPOCH)

    assert fixed.now() == EPOCH

    fixed.advance_to(2.5)
    assert fixed.now() == EPOCH + timedelta(seconds=2.5)

    fixed.observe(EPOCH + timedelta(seconds=9))
    fixed.observe(EPOCH + timedelta(seconds=4))  # a reading from the past never moves time back
    assert fixed.now() == EPOCH + timedelta(seconds=9)


def test_deterministic_ids_count_per_kind():
    fixed = clock.DeterministicClock(EPOCH)

    assert [fixed.new_id("evt"), fixed.new_id("evt"), fixed.new_id("approval")] == ["evt-000001", "evt-000002", "approval-000001"]


async def run_b2(folder, **options):
    for name, value in DEV_SECRETS.items():
        import os

        os.environ.setdefault(name, value)
    folder.mkdir()
    result = await run_scenario(load_scenario("d3"), inproc_partners(), models=MODELS, speed=0, timeout_s=30, log_dir=folder, **options)
    log = next(p for p in folder.glob("*.jsonl") if not p.name.endswith(".inputs.jsonl"))
    return result, log.read_bytes()


async def test_two_deterministic_runs_of_b2_have_byte_identical_logs_and_the_same_chain_head(tmp_path):
    _, first = await run_b2(tmp_path / "a", deterministic=True)
    _, second = await run_b2(tmp_path / "b", deterministic=True)

    assert first == second
    assert first.splitlines()[-1] == second.splitlines()[-1]  # the last line carries the hash of the whole chain before it
    journals = [next((tmp_path / name).glob("*.inputs.jsonl")).read_bytes() for name in ("a", "b")]
    assert journals[0] == journals[1]  # what came in repeats too


async def test_a_live_run_does_not_use_the_deterministic_clock(tmp_path):
    result, _ = await run_b2(tmp_path / "live")

    assert isinstance(clock.current(), clock.SystemClock)
    assert len(result.sink.events[0].id) == 36  # a uuid, not `evt-000001`
    assert abs((datetime.now(UTC) - result.sink.events[0].time).total_seconds()) < 60
