"""Commands that produce evidence: baselines, variants, benchmarks, temporal checks and explanations."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from brain import config
from brain.commands.common import _models, _seeds
from brain.config import Policy


def cmd_baseline(args: argparse.Namespace) -> int:
    from brain import baseline
    from brain.variants import policy_with

    current = asyncio.run(baseline.measure_all(args.ids or None, policy_with(baseline.PLAIN_SETS) if args.plain else None))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(baseline.dump(current))
        print(f"wrote {out}")
    if args.check:
        saved = json.loads(Path(args.check).read_text())
        saved = {key: saved[key] for key in current if key in saved} if args.ids else saved
        lines = baseline.differences(saved, current)
        print("\n".join(lines) if lines else "no differences from the baseline")
        return 1 if lines else 0
    for scenario_id, result in current.items():
        print(f"{scenario_id}: {'passed' if result['passed'] else 'FAILED'}, {len(result['decisions'])} decisions, "
              f"blocked {result['blocked'] or 'none'}, first action {result['first_action_ms']} ms")
    return 0


def cmd_variants(args: argparse.Namespace) -> int:
    from brain import baseline, variants

    ids = args.ids or baseline._all_scenario_ids()
    names = args.transforms.split(",") if args.transforms else None
    chosen = {name: variants.TRANSFORMS[name] for name in names} if names else None
    rows = asyncio.run(variants.check(ids, _seeds(args.seeds, args.count), chosen, variants.policy_with([*(baseline.PLAIN_SETS if args.plain else []), *(args.set or [])])))
    print(variants.table(rows))
    wrong = [row for row in rows if not row["passed"]]
    for row in wrong:
        print(f"DIFFERENT: {row['scenario']} {row['transform']} seed {row['seed']} "
              f"(decisions same: {row['same_decisions']}, refusals same: {row['same_blocks']})")
    print(f"{len(rows) - len(wrong)} of {len(rows)} variants decided as their base scenario")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=2) + "\n")
        print(f"wrote {args.out}")
    return 1 if wrong else 0


def cmd_forward_bench(args: argparse.Namespace) -> int:
    from brain.mind import forward_bench
    from brain.variants import policy_with

    policy = (policy_with(args.set or []) or Policy()).forward
    scores = forward_bench.score(policy, _seeds(args.seeds, args.count))
    print(forward_bench.table(scores))
    ramp = forward_bench.lead_time(_seeds(args.seeds, args.count))
    print(f"flood ramp: the Kalman tracker warned on {ramp['warned']} of {ramp['seeds']} ramps, on average {ramp['mean_lead_s']} s before the static line (worst {ramp['min_lead_s']} s)")
    if args.out:
        Path(args.out).write_text(json.dumps(scores, indent=2) + "\n")
        print(f"wrote {args.out}")
    return 0


def cmd_attention(args: argparse.Namespace) -> int:
    from brain import baseline
    from brain.mind.attention_report import attention_report
    from brain.scenario import DEV_SECRETS, inproc_partners, load_scenario, run_scenario
    from brain.variants import policy_with



    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    policy = policy_with(args.set or [])
    rows = []
    for scenario_id in args.ids or ["d3", "d4"]:
        result = asyncio.run(run_scenario(load_scenario(scenario_id), inproc_partners(), policy=policy, models=baseline.MODELS, speed=0, timeout_s=30))
        report = attention_report(result.sink.events)
        rows.append({"scenario": scenario_id, **{k: v for k, v in report.items() if k != "incidents"}})
    print("| scenario | lit | denied | below bar | team runs | slots on teamless | longest wait (readings) | inversions |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        print(f"| {r['scenario']} | {r['lit']} | {r['denied']} | {r['below_the_bar']} | {r['team_runs']} | {r['slots_on_teamless']} | {r['longest_wait_readings']} | {r['inversions']} |")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, indent=2) + "\n")
    return 0


def cmd_reliability(args: argparse.Namespace) -> int:
    from brain import reliability
    from brain.scenario import DEV_SECRETS


    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    models = _models(args) if args.llm else None
    if models is not None:
        models.embeddings.provider = "hashing"
    kinds = tuple(args.kinds.split(","))
    rows = asyncio.run(reliability.trials(args.id, args.trials, args.fault_rate, args.seed, kinds, models, llm=args.llm, pause_s=args.pause))
    summary = reliability.summary(rows)
    print(f"{args.id}: {summary['trials']} trials, {summary['passed']} passed, {summary['same_decisions']} decided as the scripted team, "
          f"{summary['fallbacks']} fallbacks, {summary['rejected']} plans rejected; "
          f"{summary['plans_placed']} placed a team plan, agreement among them {summary['plan_agreement']}")
    print("pass^k: " + ", ".join(f"k={k}: {v:.2f}" for k, v in summary["pass_hat_k"].items()))
    for row in rows:
        print(f"  trial {row['trial']}: {'pass' if row['passed'] else 'FAIL'}, "
              f"{'same decisions' if row['same_decisions'] else 'different decisions'} ({row['decisions']}), "
              f"{row['fallbacks']} fallbacks, last action {row['last_action_ms']} ms")
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=2) + "\n")
    return 0 if summary["passed"] == summary["trials"] else 1


def cmd_verify_log(args: argparse.Namespace) -> int:
    from brain import baseline
    from brain.mind.specs import SPECS, read_log, verify_log
    from brain.scenario import DEV_SECRETS, inproc_partners, load_scenario, run_scenario

    runs: list[tuple[str, list]] = [(path, read_log(path)) for path in args.logs]
    if args.scenarios:
        from brain.scenario import DEV_SECRETS

        for name, value in DEV_SECRETS.items():
            os.environ.setdefault(name, value)
        for scenario_id in baseline._all_scenario_ids():
            result = asyncio.run(run_scenario(load_scenario(scenario_id), inproc_partners(), models=baseline.MODELS, speed=0, timeout_s=30))
            runs.append((scenario_id, result.sink.events))
    if not runs:
        sys.exit("error: give a log file, or --scenarios")
    broken = 0
    for name, events in runs:
        violations = verify_log(events, complete=not args.partial)
        broken += len(violations)
        print(f"{name}: {'every promise kept' if not violations else f'{len(violations)} broken'} ({len(events)} events)")
        for v in violations:
            print(f"    {v.spec} at event {v.index}: {v.message}")
    print(f"{len(SPECS)} promises checked over {len(runs)} runs, {broken} broken")
    return 1 if broken else 0


def cmd_explain(args: argparse.Namespace) -> int:
    from brain import explain
    from brain.explain.render import to_markdown, to_sentence
    from brain.timeline import read_log

    events = read_log(Path(args.log))
    if not events:
        sys.exit(f"error: {args.log} holds no events")
    policy = config.load(Policy, "policy")
    if args.list:
        for event in events:
            data = event.get("data", {})
            if event["type"] == "brain.decision.made":
                phrase = explain.action_phrase(data.get("action", ""), data.get("params", {}), lambda zone: zone or "?")
                print(f"decision {data['decision_id']}  {phrase}")
            elif event["type"] == "brain.action.blocked":
                print(f"held {event['id']}  {data.get('check')}: {data.get('reason')}")
            elif event["type"] == "brain.incident.opened":
                print(f"incident {event['subject']}  {data.get('type')} in {data.get('zone_id')}")
        return 0
    chosen = [(explain.explain_decision, args.decision), (explain.explain_held, args.held), (explain.explain_incident, args.incident)]
    build, key = next(((b, k) for b, k in chosen if k), (None, None))
    if build is None:
        sys.exit("error: give --decision ID, --held EVENT_ID, --incident ID, or --list")
    try:
        built = build(events, key, policy=policy)
    except KeyError:
        print(f"error: nothing in {args.log} to explain for {key} (see --list)", file=sys.stderr)
        return 1
    if args.prov:
        from brain.explain.prov import to_prov

        print(json.dumps(to_prov(built), indent=2, sort_keys=True))
        return 0
    if args.bundle:
        from brain.explain.bundle import make_bundle
        from brain.scenario import DEV_SECRETS

        key = os.environ.get("BRAIN_HMAC_SECRET") or DEV_SECRETS["BRAIN_HMAC_SECRET"]
        Path(args.bundle).write_text(json.dumps(make_bundle(built, events, key), indent=2) + "\n")
        print(f"signed bundle written to {args.bundle}: check it with `brain verify-bundle {args.bundle}`")
        return 0
    print(built.model_dump_json(indent=2) if args.json else to_sentence(built) if args.sentence else to_markdown(built))
    return 0


def cmd_verify_bundle(args: argparse.Namespace) -> int:
    from brain.explain.bundle import verify_bundle
    from brain.scenario import DEV_SECRETS

    key = os.environ.get("BRAIN_HMAC_SECRET") or DEV_SECRETS["BRAIN_HMAC_SECRET"]
    ok, message = verify_bundle(json.loads(Path(args.bundle).read_text()), key)
    print(("verified: " if ok else "REFUSED: ") + message)
    return 0 if ok else 1


def cmd_rag_eval(args: argparse.Namespace) -> int:
    import json

    from brain.knowledge.embedding import make_embedder
    from brain.knowledge.evaluate import METRICS, MODES, run_evaluation

    overrides = {}
    for item in args.set or []:
        key, _, value = item.partition("=")
        overrides[key] = float(value)
    reports = []
    for provider in (["hashing", "fastembed"] if args.embedder == "both" else [args.embedder]):
        embedder, note = make_embedder(provider)
        if note:
            sys.exit(f"error: {note}")
        try:
            report = asyncio.run(run_evaluation(embedder, split=args.split, overrides=overrides, backend=args.backend))
            report["backend"] = args.backend
        except ValueError as error:
            sys.exit(f"error: {error}")
        reports.append(report)
        print(f"\n{report['embedder']}: {report['items']} items, {args.split} questions")
        for name, modes in report["splits"].items():
            print(f"  {name}")
            print(f"    {'mode':<14}" + "".join(f"{m:>10}" for m in METRICS))
            for mode in MODES:
                row = modes[mode]
                print(f"    {mode:<14}" + "".join(f"{row[m]:>10.3f}" for m in METRICS) + f"   ({row['questions']} questions)")
        for kind, modes in report["by_kind"].items():
            print(f"  {kind:<10} " + "  ".join(f"{mode} {modes[mode]['recall@3']:.2f}" for mode in MODES) + "   (recall@3)")
        print("  tight budget (2 items), multi-hop recall@2: " + "  ".join(f"{m} {report['tight_budget_multihop'][m]['recall@2']:.2f}" for m in MODES))
        no = report["nonanswer"]
        print(f"  nothing-answers questions: top vector score {no['mean_top_vector_score_nonanswer']} against {no['mean_top_vector_score_answerable']} for the rest, AUC {no['auc']}")
    if args.out:
        Path(args.out).write_text(json.dumps(reports, indent=2) + "\n")
        print(f"\nwritten to {args.out}")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    """One table of what the Brain does and how well. Exit 1 if any step fails."""
    from brain import bench

    root = config.home()
    report = asyncio.run(bench.run(bench.default_steps(root, args.quick), root))
    text = bench.markdown(report)
    print(text)
    out = Path(args.out) if args.out else root / "docs/baseline"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{report['date']}-bench.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / f"{report['date']}-bench.md").write_text(text)
    return 1 if report["failures"] else 0


def cmd_optimise_bench(args: argparse.Namespace) -> int:
    from brain.engines import bench

    seeds = _seeds(args.seeds, args.count)
    if any(s >= 1000 for s in seeds) and args.set:
        print("held-out seeds (1000 and up) are for scoring only: nothing may be tuned on them")
        return 2
    shapes = ("grid", "ring") if args.cities == "both" else (args.cities,)
    result = bench.run(seeds, shapes, args.incidents, args.units)
    print(bench.table(result))
    if args.out:
        Path(args.out).write_text(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2) + "\n")
        print(f"wrote {args.out}")
    return 0 if result["matches_brute_force"] is not False else 1
