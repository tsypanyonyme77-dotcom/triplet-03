"""Command line: `brain scenario d3`, `brain run`, `brain sleep`, `brain export-schemas`, `brain audit verify <log>`.

This file builds the parser. Each command lives in `brain/commands/`, one module per kind (run, trust, evidence, learning)."""

from __future__ import annotations

import argparse
import logging
import sys

from brain.commands.evidence import (
    cmd_attention,
    cmd_baseline,
    cmd_bench,
    cmd_explain,
    cmd_forward_bench,
    cmd_optimise_bench,
    cmd_rag_eval,
    cmd_reliability,
    cmd_variants,
    cmd_verify_bundle,
    cmd_verify_log,
)
from brain.commands.learning import cmd_ablate, cmd_academy, cmd_improve, cmd_learning_curve, cmd_sleep
from brain.commands.run import cmd_env, cmd_export_schemas, cmd_llm_check, cmd_rehearse, cmd_replay, cmd_repro, cmd_run, cmd_scenario, cmd_serve
from brain.commands.trust import cmd_audit_verify, cmd_conformance, cmd_onboard, cmd_redteam, cmd_security_check, cmd_security_report, cmd_token


def _llm_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--graph", choices=["memory", "neo4j", "qdrant"], help="override graph.backend from partners.yaml")
    parser.add_argument("--departments", action=argparse.BooleanOptionalAction, default=True,
                        help="Fire, Ambulance and medical, Traffic control, Disaster response and Utilities each have an agent desk, as Police has its team (default on; --no-departments for rules only)")
    parser.add_argument("--llm", action="store_true", help="run the department team as LLM agents (default: scripted stand-ins)")
    parser.add_argument("--model", help="use this model for every role, e.g. ollama:qwen3:8b (implies --llm)")
    parser.add_argument("--cassette", help="keep or replay every model call in this file (see --cassette-mode)")
    parser.add_argument("--cassette-mode", choices=["record", "replay", "auto"], default="auto", help="with --cassette: record, replay with no model, or replay what it has and record the rest")
    parser.add_argument("--budget", type=float, help="seconds a deliberation may take before the reflex decision stands")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brain", description="City Brain layer")
    commands = parser.add_subparsers(dest="command", required=True)

    scenario = commands.add_parser("scenario", help="run one Test Book scenario against the mocks")
    scenario.add_argument("id", help="scenario id, e.g. d3")
    scenario.add_argument("--deterministic", action="store_true", help="a fixed epoch and numbered ids: two runs of one scenario give the same log bytes")
    scenario.add_argument("--speed", type=float, default=1.0, help="playback speed; 0 releases all events at once")
    scenario.add_argument("--inproc", action="store_true", help="run the mocks inside this process instead of as servers")
    scenario.add_argument("--no-spawn", action="store_true", help="use mock servers that are already running")
    _llm_flags(scenario)
    scenario.add_argument("--config", help="path to partners.yaml")
    scenario.add_argument("--timeout", type=float, default=60.0)
    scenario.add_argument("--quiet", action="store_true", help="do not print the timeline")
    scenario.set_defaults(handler=cmd_scenario)

    run = commands.add_parser("run", help="run against the partners configured in config/partners.yaml")
    run.add_argument("--config", help="path to partners.yaml")
    _llm_flags(run)
    run.add_argument("--verbose", action="store_true", help="also print every reading and verdict")
    run.add_argument("--fresh", action="store_true", help="forget the state saved by an earlier run instead of continuing it")
    run.set_defaults(handler=cmd_run)

    repro = commands.add_parser("repro", help="run a scenario again and report, level by level, what changed: decisions, stream, bytes, prompt")
    repro.add_argument("id", help="scenario id, e.g. d3")
    repro.add_argument("--runs", type=int, default=5)
    repro.add_argument("--processes", action="store_true", help="each run in a fresh process with its own PYTHONHASHSEED")
    repro.add_argument("--deterministic", action="store_true", help="a fixed epoch and numbered ids, so the bytes can repeat")
    repro.add_argument("--json", action="store_true")
    repro.set_defaults(handler=cmd_repro)

    onboarding = commands.add_parser("onboard", help="propose the renames and units for a Twin that names things differently (prints; never edits config)")
    onboarding.add_argument("--sample", help="a JSON file of readings, or {\"readings\": [...]}")
    onboarding.add_argument("--twin", help="or the Twin's MCP URL: sample it live")
    onboarding.add_argument("--readings", type=int, default=50)
    onboarding.add_argument("--yaml", action="store_true", help="print the config lines")
    onboarding.set_defaults(handler=cmd_onboard)

    report = commands.add_parser("security-report", help="run the evidence for every threat in docs/SECURITY.md and say which are covered, failing or open")
    report.add_argument("--out", help="write the report here, e.g. docs/security/2026-11-05.md")
    report.set_defaults(handler=cmd_security_report)

    minting = commands.add_parser("token", help="mint a short-lived API token (or --revoke one by id)")
    minting.add_argument("--sub", default="operator")
    minting.add_argument("--scope", default="read", help="comma separated: read, analyse, push, approve, admin")
    minting.add_argument("--ttl", default="8h", help="e.g. 30m, 8h, 2d")
    minting.add_argument("--revoke", metavar="ID")
    minting.set_defaults(handler=cmd_token)

    llm_check = commands.add_parser("llm-check", help="is the hosted model answering: the key, the quota left (one one-token call per model; run with --env-file .env)")
    llm_check.set_defaults(handler=cmd_llm_check)

    attack = commands.add_parser("redteam", help="attack the Brain 24 ways; every attack must be refused")
    attack.add_argument("--brain", help="a running Brain's URL (tokens come from BRAIN_TOKEN_READ, TWIN_PUSH_TOKEN, ...); omit to attack one in process")
    attack.add_argument("--json", action="store_true")
    attack.add_argument("--out", help="write the report as Markdown")
    attack.set_defaults(handler=cmd_redteam)

    conformance = commands.add_parser("conformance", help="check a Twin, a Guardian or a Brain against the contract (no arguments: the shipped mocks and this Brain)")
    conformance.add_argument("--twin", help="the Twin's MCP URL, e.g. http://twin:8765/mcp")
    conformance.add_argument("--guardian", help="the Guardian's base URL, e.g. http://guardian:8766")
    conformance.add_argument("--brain", help="a Brain's base URL, e.g. http://brain:8080")
    conformance.add_argument("--twin-secret-env", default="TWIN_HMAC_SECRET", help="env var holding the secret the Twin signs readings with")
    conformance.add_argument("--brain-secret-env", default="BRAIN_HMAC_SECRET", help="env var holding the secret the Brain signs calls with (for the actuator probe)")
    conformance.add_argument("--token-env", help="env var holding a bearer token for a Brain that requires one")
    conformance.add_argument("--probe-actuators", action="store_true", help="also command the Twin's actuators with test calls (only against a test Twin)")
    conformance.add_argument("--json", action="store_true")
    conformance.add_argument("--out", help="also write a Markdown report here, e.g. docs/conformance/2026-11-04.md")
    conformance.set_defaults(handler=cmd_conformance)

    check = commands.add_parser("security-check", help="run the security invariants and the API edge tests")
    check.set_defaults(handler=cmd_security_check)

    env = commands.add_parser("env", help="print what a run depends on (code, locked packages, models, clock) so two runs can be compared; no secrets")
    env.set_defaults(handler=cmd_env)

    replay = commands.add_parser("replay", help="play a run's input journal back into the Brain and check that it decides the same")
    replay.add_argument("journal", help="logs/<run>.inputs.jsonl")
    replay.add_argument("--timeline", help="the run's log to compare with (default: the log next to the journal)")
    replay.add_argument("--current-config", action="store_true", help="replay under the current config/policy.yaml instead of the recorded policy")
    replay.add_argument("--allow-config-change", action="store_true", help="with --current-config: accept a config that differs from the recorded one")
    replay.set_defaults(handler=cmd_replay)

    serve = commands.add_parser("serve", help="HTTP API, live event stream and timeline screen")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--mocks", choices=["inproc", "spawn"], default="inproc", help="how scenario runs get their Twin and Guardian")
    serve.add_argument("--live", action="store_true", help="connect to the partners in config/partners.yaml instead of mocks")
    serve.add_argument("--fresh", action="store_true", help="forget the state saved by an earlier run instead of continuing it")
    serve.add_argument("--config", help="path to partners.yaml")
    serve.add_argument("--episodes", help="keep closed incidents here as episodes (default: brain.episodes_dir)")
    serve.add_argument("--learned", help="keep the reflexes sleep promoted here (default: brain.learned_dir)")
    serve.add_argument("--approvals", action="store_true", help="a valve or grid call waits for a person: Approve and Deny buttons appear on the screen (approval.mode: human)")
    serve.add_argument("--tls-cert", help="serve https with this certificate (needs --tls-key)")
    serve.add_argument("--tls-key")
    serve.add_argument("--tls-client-ca", help="mutual TLS: refuse a client whose certificate this authority did not sign")
    _llm_flags(serve)
    serve.set_defaults(handler=cmd_serve)

    export = commands.add_parser("export-schemas", help="write the JSON Schemas of every contract message")
    export.add_argument("--out")
    export.set_defaults(handler=cmd_export_schemas)

    audit = commands.add_parser("audit", help="audit log tools")
    audit_commands = audit.add_subparsers(dest="audit_command", required=True)
    verify = audit_commands.add_parser("verify", help="recompute the hash chain of a log file")
    verify.add_argument("log")
    verify.set_defaults(handler=cmd_audit_verify)

    baseline = commands.add_parser("baseline", help="record or check what the Brain decides on the Test Book")
    baseline.add_argument("ids", nargs="*", help="scenario ids (default: every b* scenario)")
    baseline.add_argument("--out", help="write the measurements to this JSON file")
    baseline.add_argument("--check", help="compare with this saved JSON file; exit 1 on any difference")
    baseline.add_argument("--plain", action="store_true", help="measure with every solver off (the pipeline before 6 Nov), to check the older frozen files")
    baseline.set_defaults(handler=cmd_baseline)

    sleeping = commands.add_parser("sleep", help="learn from stored episodes: promote repeated team plans to reflexes, through a gate")
    sleeping.add_argument("--episodes", help="folder of episodes (default: brain.episodes_dir)")
    sleeping.add_argument("--learned", help="folder for promoted rules (default: brain.learned_dir)")
    sleeping.add_argument("--rollback", metavar="ID|all", help="forget one learned rule, or all of them, and do nothing else")
    sleeping.add_argument("--dry-run", action="store_true", help="run every check but write nothing")
    sleeping.add_argument("--config", help="path to partners.yaml")
    sleeping.set_defaults(handler=cmd_sleep)

    curve = commands.add_parser("learning-curve", help="run a scenario several times with sleep in between and show what learning saves")
    curve.add_argument("scenario", nargs="?", default="d3")
    curve.add_argument("--runs", type=int, default=3)
    curve.add_argument("--out", help="write the rows to this JSON file")
    curve.set_defaults(handler=cmd_learning_curve)

    ablation = commands.add_parser("ablate", help="switch each region off in turn, replay the Test Book, and show what each one is worth")
    ablation.add_argument("ids", nargs="*", help="scenario ids (default: every scenario)")
    ablation.add_argument("--out", help="write the result to this JSON file")
    ablation.set_defaults(handler=cmd_ablate)

    varied = commands.add_parser("variants", help="run held-out variants of the Test Book (shifted, reseeded, decoyed); each must decide as its base does")
    varied.add_argument("ids", nargs="*", help="scenario ids (default: every b* scenario)")
    varied.add_argument("--seeds", default="held-out", help="held-out (seeds 1000 and up, the default), train (under 1000) or a range such as 1000-1004")
    varied.add_argument("--count", type=int, default=3, help="how many seeds to take from held-out or train")
    varied.add_argument("--transforms", help="comma-separated: shift_time, reseed, decoy (default: all)")
    varied.add_argument("--set", action="append", metavar="SECTION.FIELD=VALUE", help="lay a policy setting over the defaults, e.g. workspace.corroboration_by=cause (repeatable)")
    varied.add_argument("--out", help="write the rows to this JSON file")
    varied.add_argument("--plain", action="store_true", help="run with every solver off")
    varied.set_defaults(handler=cmd_variants)

    optimise = commands.add_parser("optimise-bench", help="how much solving the dispatch together saves over nearest-first, on random cities (checked against brute force)")
    optimise.add_argument("--seeds", default="held-out", help="held-out (1000 and up), train (under 1000) or a range such as 0-4")
    optimise.add_argument("--count", type=int, default=50)
    optimise.add_argument("--cities", choices=["grid", "ring", "both"], default="both")
    optimise.add_argument("--incidents", type=int, default=4)
    optimise.add_argument("--units", type=int, default=4, help="stations (one unit each)")
    optimise.add_argument("--set", action="append", help="refused on held-out seeds")
    optimise.add_argument("--out", help="write the summary to this JSON file")
    optimise.set_defaults(handler=cmd_optimise_bench)

    bench = commands.add_parser("forward-bench", help="score the forward models on synthetic sensor streams with a known truth (false doubts, delay, spikes, recovery)")
    bench.add_argument("--seeds", default="held-out", help="held-out (1000 and up), train (under 1000) or a range such as 0-4")
    bench.add_argument("--count", type=int, default=5)
    bench.add_argument("--set", action="append", metavar="SECTION.FIELD=VALUE", help="a policy setting, e.g. forward.calibration=conformal (repeatable)")
    bench.add_argument("--out", help="write the scores to this JSON file")
    bench.set_defaults(handler=cmd_forward_bench)

    attention = commands.add_parser("attention", help="where the workspace's slots and the team's runs went on the demo scenarios (d3, d4 by default)")
    attention.add_argument("ids", nargs="*")
    attention.add_argument("--set", action="append", metavar="SECTION.FIELD=VALUE", help="a policy setting, e.g. workspace.slots_for=team (repeatable)")
    attention.add_argument("--out", help="write the rows to this JSON file")
    attention.set_defaults(handler=cmd_attention)

    reliable = commands.add_parser("reliability", help="run a scenario again and again under injected faults (or against the real model) and report how often the team's plan held")
    reliable.add_argument("id", nargs="?", default="d3")
    reliable.add_argument("--trials", type=int, default=5)
    reliable.add_argument("--fault-rate", type=float, default=0.0, help="chance that a role call fails (injected faults; ignored with --llm)")
    reliable.add_argument("--kinds", default="error,garbage", help="which faults: error, garbage")
    reliable.add_argument("--seed", type=int, default=0)
    reliable.add_argument("--pause", type=float, default=0.0, help="seconds between trials (use about 65 with --llm on the free plan)")
    reliable.add_argument("--out", help="write the rows and the summary to this JSON file")
    _llm_flags(reliable)
    reliable.set_defaults(handler=cmd_reliability)

    verify = commands.add_parser("verify-log", help="check the temporal promises (trust before action, nothing after close, every unit home...) on saved logs or on every scenario")
    verify.add_argument("logs", nargs="*", help="timeline .jsonl files, for example from logs/")
    verify.add_argument("--scenarios", action="store_true", help="also run every scenario and check its timeline")
    verify.add_argument("--partial", action="store_true", help="the log is still being written: skip the end-of-run promises")
    verify.set_defaults(handler=cmd_verify_log)

    explainer = commands.add_parser("explain", help="why the Brain decided, or held back, from a saved log: the steps, the gate, what it relied on, what would have changed it")
    explainer.add_argument("log", help="a timeline .jsonl file, for example from logs/")
    explainer.add_argument("--list", action="store_true", help="list the decisions, held actions and incidents in the log")
    explainer.add_argument("--decision", metavar="ID", help="explain one decision, for example dec-0001")
    explainer.add_argument("--held", metavar="EVENT_ID", help="explain one held action by the id of its brain.action.blocked event")
    explainer.add_argument("--incident", metavar="ID", help="tell the story of one incident")
    explainer.add_argument("--json", action="store_true", help="the explanation as JSON")
    explainer.add_argument("--sentence", action="store_true", help="only the one-line version")
    explainer.add_argument("--prov", action="store_true", help="print the explanation as W3C PROV-JSON")
    explainer.add_argument("--bundle", metavar="FILE", help="write the explanation and the log lines it rests on as a signed file an auditor can check offline")
    explainer.set_defaults(handler=cmd_explain)

    rag = commands.add_parser("rag-eval", help="measure retrieval on tests/data/rag_eval.yaml: recall, rank and nDCG for dense, keyword, hybrid and hybrid+graph search")
    rag.add_argument("--embedder", choices=["hashing", "fastembed", "both"], default="both")
    rag.add_argument("--split", choices=["all", "design", "heldout"], default="all")
    rag.add_argument("--backend", choices=["memory", "qdrant", "qdrant-hybrid"], default="memory", help="where the vectors live; qdrant-hybrid also lets Qdrant do the keyword search and the fusion")
    rag.add_argument("--set", action="append", metavar="knowledge.KEY=VALUE", help="try a retrieval switch (knowledge.mmr, knowledge.utility_weight); design questions only")
    rag.add_argument("--out", help="write the numbers to this JSON file")
    rag.set_defaults(handler=cmd_rag_eval)

    checker = commands.add_parser("verify-bundle", help="check a signed explanation bundle offline: the signature, each log line's own hash, every step's line")
    checker.add_argument("bundle", help="a file made by `brain explain --bundle`")
    checker.set_defaults(handler=cmd_verify_bundle)

    benching = commands.add_parser("bench", help="run the scenarios, baselines, interop, security and benchmark steps and write one table (--quick skips the slow ones)")
    benching.add_argument("--quick", action="store_true")
    benching.add_argument("--out", help="folder for <date>-bench.json and .md (default docs/baseline)")
    benching.set_defaults(handler=cmd_bench)

    improving = commands.add_parser("improve", help="measure, ask the Academy for changes inside its fence, verify everything still holds, and (with --apply) write the overlay")
    improving.add_argument("--apply", action="store_true")
    improving.add_argument("--steps", type=int, default=3)
    improving.add_argument("--max-changes", type=int, default=2)
    improving.add_argument("--tuned", help="the Academy's folder (default: brain.tuned_dir or tuned)")
    improving.add_argument("--out", help="the report (default: docs/improvement/<date>.md)")
    improving.set_defaults(handler=cmd_improve)

    academic = commands.add_parser("academy", help="the Brain tunes its own parameters, inside a fence, and shows the evidence")
    academic.add_argument("--steps", type=int, default=12, help="how many promotions to try at most")
    academic.add_argument("--max-changes", type=int, default=6, help="the most parameters an overlay may hold")
    academic.add_argument("--dry-run", action="store_true", help="find what it would promote, write nothing")
    academic.add_argument("--tuned", help="folder for the overlay and its history (default: brain.tuned_dir, else ./tuned)")
    academic.add_argument("--show", action="store_true", help="print the overlay and the evidence for each value")
    academic.add_argument("--rollback", metavar="PATH|all", help="remove one tuned value, or all of them")
    academic.add_argument("--audit", action="store_true", help="re-score the overlay on new stories and retire what no longer helps")
    academic.set_defaults(handler=cmd_academy)

    rehearsal = commands.add_parser("rehearse", help="the whole freeze check, offline: Test Book, baselines, learning curve, ablations, poisoning, screens")
    rehearsal.add_argument("--out", help="folder for the dated report (default: docs/rehearsal)")
    rehearsal.add_argument("--quick", action="store_true", help="a smaller suite, for a fast check")
    rehearsal.add_argument("--no-screens", action="store_true", help="skip the screenshots and the canopy smoke test")
    rehearsal.set_defaults(handler=cmd_rehearse)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    # The timeline is the output; per-request client logs would bury it.
    for noisy in ("httpx", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    sys.exit(args.handler(args))


if __name__ == "__main__":
    main()
