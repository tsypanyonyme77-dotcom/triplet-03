"""Commands for learning: sleep, the learning curve, ablations, improvement and the Academy."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from brain import config
from brain.commands.common import _log_dir
from brain.config import PartnersConfig, Policy
from brain.timeline import ConsoleSink, JsonlSink, Timeline


def cmd_sleep(args: argparse.Namespace) -> int:
    from brain.mind.sleep import rollback, sleep

    partners = config.load(PartnersConfig, "partners", args.config)
    policy = config.load(Policy, "policy")

    def folder(given: str | None, configured: str | None, name: str) -> Path:
        chosen = given or configured
        if not chosen:
            sys.exit(f"error: no {name} folder: pass --{name} or set brain.{name}_dir in partners.yaml")
        return Path(chosen) if Path(chosen).is_absolute() else config.home() / chosen

    learned = folder(args.learned, partners.brain.learned_dir, "learned")
    if args.rollback:
        gone = rollback(learned, args.rollback)
        print(f"forgot {', '.join(gone) if gone else 'nothing'}")
        return 0
    episodes = folder(args.episodes, partners.brain.episodes_dir, "episodes")
    log_path = _log_dir(partners) / f"sleep-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    sinks = [ConsoleSink(), JsonlSink(log_path)]
    report = asyncio.run(sleep(episodes, learned, policy, Timeline(sinks), dry_run=args.dry_run))
    print(f"\n{report.episodes} episodes ({report.unreadable} unreadable), {report.candidates} candidate lessons: "
          f"{len(report.promoted)} promoted, {len(report.rejected)} rejected, {len(report.skipped)} already known"
          f"{', dry run: nothing written' if args.dry_run else ''}. {report.seconds} s. log: {log_path}")
    for item in report.rejected:
        print(f"  rejected {item['rule']} at {item['check']}: {item['reason']}")
    return 0


def cmd_learning_curve(args: argparse.Namespace) -> int:
    import tempfile

    from brain.mind.curve import dump, learning_curve

    policy = config.load(Policy, "policy")
    with tempfile.TemporaryDirectory(prefix="learning-curve-") as workdir:
        rows = asyncio.run(learning_curve(args.scenario, args.runs, Path(workdir), policy))
    print(f"{'run':>3}  {'team runs':>9}  {'learned plans used':>18}  {'time to last action':>19}  same decisions as run 1")
    for row in rows:
        print(f"{row['run']:>3}  {row['team_runs']:>9}  {row['compiled_plans']:>18}  {str(row['last_action_ms']) + ' ms':>19}  "
              f"{'yes' if row['decisions_equal_to_run_1'] else 'NO'}")
    if args.out:
        Path(args.out).write_text(dump(rows))
        print(f"wrote {args.out}")
    return 0 if all(row["decisions_equal_to_run_1"] for row in rows) else 1


def cmd_ablate(args: argparse.Namespace) -> int:
    import tempfile

    from brain.mind.ablate import ablate, dump, table
    from brain.mind.sleep import DEFAULT_SUITE

    with tempfile.TemporaryDirectory(prefix="ablate-") as workdir:
        result = asyncio.run(ablate(args.ids or DEFAULT_SUITE, Path(workdir)))
    print(table(result))
    if args.out:
        Path(args.out).write_text(dump(result))
        print(f"wrote {args.out}")
    return 0


def cmd_improve(args: argparse.Namespace) -> int:
    """Measure, ask the Academy, verify, and (with --apply) write its overlay only if every check passes."""
    from brain import baseline, redteam
    from brain.contracts import CONTRACT_VERSION  # noqa: F401
    from brain.engines import bench
    from brain.knowledge.embedding import HashingEmbedder
    from brain.knowledge.evaluate import run_evaluation
    from brain.mind import academy
    from brain.mind import improve as loop
    from brain.mind.forward_bench import score
    from brain.scenario import DEV_SECRETS

    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    folder = Path(args.tuned or config.load(PartnersConfig, "partners").brain.tuned_dir or "tuned")
    folder = folder if folder.is_absolute() else config.home() / folder

    async def measure() -> dict[str, Any]:
        forward = score(Policy().forward, range(1000, 1003))
        retrieval = (await run_evaluation(HashingEmbedder(), split="heldout"))["splits"]["heldout"]["hybrid"]
        dispatch = bench.run(list(range(1000, 1020)))
        return {"forward-bench false doubts per 1000 (calm streams)": round(sum(v["false_doubts_per_1000"] for k, v in forward.items() if k in academy.CALM_STREAMS) / len(academy.CALM_STREAMS), 3),
                "rag-eval hybrid recall@3 (held-out, hashing)": round(retrieval["recall@3"], 3),
                "optimise-bench mean regret (held-out)": dispatch["mean_regret"]}

    async def propose(dry: bool) -> Any:
        return await academy.Academy(folder, max_changes=args.max_changes).run(args.steps, dry)

    async def verify() -> list[loop.Check]:
        checks = []
        current = await baseline.measure_all()
        for path in sorted((config.home() / "docs/baseline").glob("*-frozen.json")):
            saved = json.loads(path.read_text())
            lines = baseline.differences({k: saved[k] for k in current if k in saved}, current)
            checks.append(loop.Check(f"decides as recorded in {path.name}", not lines, "no differences" if not lines else lines[0]))
        attacks = await redteam.run_in_process()
        checks.append(loop.Check("red team", all(a.status == "pass" for a in attacks), f"{sum(a.status == 'pass' for a in attacks)} of {len(attacks)} attacks refused"))
        return checks

    result = asyncio.run(loop.improve(folder, apply=args.apply, measure=measure, propose=propose, verify=verify))
    text = loop.markdown(datetime.now(UTC).strftime("%Y-%m-%d"), result)
    print(text)
    out = Path(args.out) if args.out else config.home() / "docs/improvement" / f"{datetime.now(UTC).strftime('%Y-%m-%d')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return 0 if all(c.passed for c in result.checks) else 1


def cmd_academy(args: argparse.Namespace) -> int:
    from brain.mind import academy

    folder = Path(args.tuned or config.load(PartnersConfig, "partners").brain.tuned_dir or "tuned")
    folder = folder if folder.is_absolute() else config.home() / folder
    if args.show:
        print(academy.show(folder))
        return 0
    if args.rollback:
        gone = academy.rollback(folder, args.rollback)
        print(f"rolled back: {', '.join(gone)}" if gone else "nothing to roll back")
        return 0
    from brain.scenario import DEV_SECRETS

    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    if args.audit:
        retired = asyncio.run(academy.audit(folder))
        print(f"retired by the audit: {', '.join(retired)}" if retired else "every tuned value still beats the shipped one on new stories")
        return 0
    report = asyncio.run(academy.Academy(folder, max_changes=args.max_changes).run(args.steps, args.dry_run))
    print(f"{report.steps} step(s); loss {report.start_loss:.3f} -> {report.end_loss:.3f}")
    for row in report.promoted:
        print(f"  PROMOTED {row['path']}: {row['from']} -> {row['to']} (design gain {row['design_gain']}, held-out gain {row['held_out_gain']})")
    for row in report.rejected:
        print(f"  rejected {row['path']}: {row['from']} -> {row['to']} at {row['check']}: {row['reason'][:150]}")
    if not report.promoted and not report.rejected:
        print("  nothing on the surface improved the loss")
    print(f"{'(dry run: nothing written) ' if args.dry_run else ''}overlay folder: {folder}")
    return 0
