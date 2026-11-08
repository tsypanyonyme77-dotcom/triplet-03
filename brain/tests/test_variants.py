"""Variants: the held-out set. A variant of a scenario must be decided exactly as its base is."""

import copy

import pytest

from brain.scenario import expand_streams, load_scenario
from brain.variants import HELD_OUT_SEEDS, TRAIN_SEEDS, TRANSFORMS, check, decoy, load_raw, reseed, shift_time, variants


def test_train_and_held_out_seeds_do_not_overlap():
    assert not set(TRAIN_SEEDS) & set(HELD_OUT_SEEDS)
    assert max(TRAIN_SEEDS) < min(HELD_OUT_SEEDS)


def test_shift_time_moves_every_event_and_stream_and_nothing_else():
    base = load_raw("d2")

    moved = shift_time(base, 1000)

    delta = moved["events"][0]["at_ms"] - base["events"][0]["at_ms"]
    assert delta > 0
    assert [e["at_ms"] - b["at_ms"] for e, b in zip(moved["events"], base["events"], strict=True)] == [delta] * len(base["events"])
    assert moved["streams"][0]["from_ms"] == base["streams"][0]["from_ms"] + delta
    assert moved["streams"][0]["to_ms"] == base["streams"][0]["to_ms"] + delta
    assert {k: v for k, v in moved.items() if k not in ("events", "streams")} == {k: v for k, v in base.items() if k not in ("events", "streams")}
    assert base == load_raw("d2"), "the transform must not touch its input"


def test_reseed_changes_only_stream_seeds():
    base = load_raw("d2")

    changed = reseed(base, 1003)

    assert changed["streams"][0]["seed"] == base["streams"][0]["seed"] + 1003
    assert {**changed["streams"][0], "seed": 0} == {**base["streams"][0], "seed": 0}
    assert changed["events"] == base["events"]


def test_reseed_changes_nothing_in_a_scenario_without_streams():
    assert reseed(load_raw("d3"), 1000) == load_raw("d3")


def test_a_decoy_stream_is_calm_and_in_an_untouched_zone():
    base = load_raw("d3")
    used = {e["zone_id"] for e in base["events"]}

    changed = decoy(base, 1002)

    (stream,) = [s for s in changed["streams"] if s["sensor_id"].startswith("decoy-")]
    assert stream["zone_id"] not in used
    assert stream["type"] == "traffic_camera" and stream["base"]["congestion_score"] <= 0.3
    assert stream["to_ms"] > max(e["at_ms"] for e in base["events"])
    assert len(expand_streams(changed)["events"]) > len(base["events"])


def test_variants_skip_a_transform_that_changes_nothing_and_label_the_rest():
    found = variants(load_raw("d3"), [1000])

    assert {v["transform"] for v in found} == {"shift_time", "decoy"}  # b2 has no streams to reseed
    assert all(v["variant_of"] == "d3" and v["seed"] == 1000 for v in found)


@pytest.mark.parametrize("scenario_id", ["d3", "d2"])
async def test_every_transform_keeps_the_scenario_valid_and_the_base_decisions(scenario_id):
    rows = await check([scenario_id], [1000])

    assert rows, "no variant was produced"
    assert all(row["same_decisions"] and row["same_blocks"] for row in rows), rows


async def test_check_reports_a_row_per_variant():
    rows = await check(["d2"], [1000, 1001])

    assert len(rows) == 2 * len(TRANSFORMS)
    assert {row["scenario"] for row in rows} == {"d2"}
    assert {row["seed"] for row in rows} == {1000, 1001}


async def test_a_transform_that_changes_decisions_is_reported():
    def break_it(scenario, seed):
        broken = copy.deepcopy(scenario)
        broken["guardian"] = {"down": True}
        return broken

    rows = await check(["d3"], [1000], {"break_it": break_it})

    (row,) = rows
    assert row["transform"] == "break_it" and not row["same_decisions"]
    assert row["passed"] is False


def test_load_raw_keeps_streams_unexpanded_and_the_topology_resolved():
    raw = load_raw("d2")

    assert raw["streams"] and isinstance(raw["topology"], dict)
    assert expand_streams(raw)["events"] == load_scenario("d2")["events"]


def test_policy_settings_are_laid_over_the_defaults():
    from brain.variants import policy_with

    policy = policy_with(["workspace.corroboration_by=cause", "forward.z_threshold=5.5", "workspace.bids=false"])

    assert policy.workspace.corroboration_by == "cause" and policy.forward.z_threshold == 5.5 and policy.workspace.bids is False
    assert policy_with([]) is None
