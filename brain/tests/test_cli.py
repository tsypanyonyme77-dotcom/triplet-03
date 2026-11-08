"""The command line: options that change what the Brain loads, without editing the shipped config."""

from brain.cli import build_parser
from brain.commands.common import serve_partners


def test_serve_takes_episodes_and_learned_flags():
    args = build_parser().parse_args(["serve", "--episodes", "my-episodes", "--learned", "my-learned"])

    partners = serve_partners(args)

    assert partners.brain.episodes_dir == "my-episodes"
    assert partners.brain.learned_dir == "my-learned"


def test_serve_without_the_flags_keeps_what_the_config_says():
    args = build_parser().parse_args(["serve"])

    partners = serve_partners(args)

    assert partners.brain.episodes_dir is None
    assert partners.brain.learned_dir is None


def test_repro_takes_a_scenario_runs_and_processes():
    args = build_parser().parse_args(["repro", "d3", "--runs", "3", "--processes"])

    assert (args.id, args.runs, args.processes) == ("d3", 3, True)
    assert build_parser().parse_args(["repro", "d3"]).runs == 5


def test_repro_and_scenario_take_a_deterministic_flag():
    assert build_parser().parse_args(["repro", "d3", "--deterministic"]).deterministic is True
    assert build_parser().parse_args(["scenario", "d3", "--deterministic"]).deterministic is True
    assert build_parser().parse_args(["scenario", "d3"]).deterministic is False


def test_deterministic_without_inproc_is_refused_because_spawned_mocks_use_the_real_clock(capsys):
    from brain.cli import cmd_scenario

    args = build_parser().parse_args(["scenario", "d3", "--deterministic"])

    assert cmd_scenario(args) == 2
    assert "--inproc" in capsys.readouterr().err


def test_conformance_takes_urls_secrets_and_the_probe_flag():
    args = build_parser().parse_args(["conformance", "--twin", "http://t/mcp", "--guardian", "http://g", "--brain", "http://b", "--probe-actuators", "--json"])

    assert (args.twin, args.guardian, args.brain, args.probe_actuators, args.json) == ("http://t/mcp", "http://g", "http://b", True, True)


def test_conformance_with_no_arguments_passes_on_the_shipped_mocks(capsys):
    from brain.cli import cmd_conformance

    code = cmd_conformance(build_parser().parse_args(["conformance"]))

    assert code == 0 and "0 failed" in capsys.readouterr().out


def test_serve_with_approvals_makes_a_high_impact_call_wait_for_a_person():
    partners = serve_partners(build_parser().parse_args(["serve", "--approvals"]))

    assert partners.approval.mode == "human"
    assert serve_partners(build_parser().parse_args(["serve"])).approval.mode == "off"
