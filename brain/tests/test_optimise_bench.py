"""The dispatch bench: the solver is checked against brute force, the bench repeats for a seed, and held-out seeds are never tuned on."""

from brain.cli import build_parser, cmd_optimise_bench
from brain.engines import bench


def test_the_solver_matches_brute_force_on_small_instances():
    result = bench.run(list(range(0, 15)), incidents=5, units=3)

    assert result["matches_brute_force"] is True and result["instances"] == 30


def test_the_bench_is_deterministic_for_a_seed():
    strip = lambda r: {k: v for k, v in r.items() if k not in ("rows", "solve_ms_p50", "solve_ms_p99")}  # noqa: E731  times are measured

    assert strip(bench.run([1000, 1001])) == strip(bench.run([1000, 1001]))


def test_the_solver_is_never_worse_than_nearest_first():
    assert all(r["regret"] >= 0 for r in bench.run(list(range(1000, 1030)))["rows"])


def test_held_out_seeds_start_at_1000_and_the_bench_refuses_to_tune_on_them():
    args = build_parser().parse_args(["optimise-bench", "--seeds", "held-out", "--set", "optimiser.unmet_penalty=5"])

    assert cmd_optimise_bench(args) == 2
