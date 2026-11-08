"""`brain bench`: one command, one table of what the Brain does and how well, for the report and for the day before the demo.

Each step produces one number or one verdict. A step that raises is reported as a failure with its error, never swallowed, and the run exits 1.
`--quick` skips the slow steps (the variants, the ablations, the learning curve). The JSON is for comparing two runs; the Markdown is for people.
"""

from __future__ import annotations

import json
import platform
import subprocess
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

Step = Callable[[], Awaitable[Any]]


def _commit(root: Path) -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=False).stdout.strip()
        return sha + (" + uncommitted changes" if dirty else "")
    except Exception:  # noqa: BLE001 - git may be absent; the report says unknown
        return "unknown"


def default_steps(root: Path, quick: bool) -> dict[str, Step]:
    import os

    from brain import baseline, conformance, redteam
    from brain.engines import bench as dispatch_bench
    from brain.knowledge.embedding import HashingEmbedder
    from brain.knowledge.evaluate import run_evaluation
    from brain.mind import academy
    from brain.mind.forward_bench import lead_time, score
    from brain.mind.specs import verify_log
    from brain.scenario import DEV_SECRETS, inproc_partners, load_scenario, run_scenario

    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)

    async def scenarios() -> dict[str, Any]:
        ids = baseline._all_scenario_ids()
        passed, broken, decisions = 0, 0, 0
        for scenario_id in ids:
            result = await run_scenario(load_scenario(scenario_id), inproc_partners(), models=baseline.MODELS, speed=0, timeout_s=30)
            passed += result.passed
            broken += len(verify_log(result.sink.events))
            decisions += len(result.sink.of("brain.decision.made"))
        return {"scenarios": len(ids), "passed": passed, "temporal_promises_broken": broken, "decisions": decisions}

    async def baselines() -> dict[str, Any]:
        current = await baseline.measure_all()
        out = {}
        for path in sorted((root / "docs/baseline").glob("*-frozen.json")):
            saved = json.loads(path.read_text())
            out[path.name] = "no differences" if not (lines := baseline.differences({k: saved[k] for k in current if k in saved}, current)) else lines[0]
        return out

    async def dispatch() -> dict[str, Any]:
        r = dispatch_bench.run(list(range(1000, 1050)))
        return {k: r[k] for k in ("instances", "differ_share", "mean_regret", "solve_ms_p99", "matches_brute_force")}

    async def retrieval() -> dict[str, Any]:
        r = (await run_evaluation(HashingEmbedder(), split="all"))["splits"]
        return {"hybrid_recall@3_design": round(r["design"]["hybrid"]["recall@3"], 3), "hybrid_recall@3_heldout": round(r["heldout"]["hybrid"]["recall@3"], 3), "embedder": "hashing"}

    async def forward() -> dict[str, Any]:
        s = score(academy.Policy().forward, range(1000, 1005))
        ramp = lead_time(range(1000, 1020))
        return {"false_doubts_per_1000_calm": round(sum(s[n]["false_doubts_per_1000"] for n in academy.CALM_STREAMS) / len(academy.CALM_STREAMS), 3),
                "flood_ramps_warned": f"{ramp['warned']} of {ramp['seeds']}", "flood_warning_mean_lead_s": ramp["mean_lead_s"]}

    async def interop() -> dict[str, Any]:
        results = await _conformance(conformance)
        return {"conformance_failed": sum(r.status == "fail" for r in results), "conformance_passed": sum(r.status == "pass" for r in results)}

    async def attacks() -> dict[str, Any]:
        results = await redteam.run_in_process()
        return {"attacks": len(results), "refused": sum(r.status == "pass" for r in results)}

    steps: dict[str, Step] = {"scenarios": scenarios, "baselines": baselines, "dispatch": dispatch, "retrieval": retrieval, "forward": forward, "conformance": interop, "redteam": attacks}
    if not quick:
        from brain import variants
        from brain.mind.curve import learning_curve

        async def variant_run() -> dict[str, Any]:
            rows = await variants.check(baseline._all_scenario_ids(), range(1000, 1005))
            return {"variants": len(rows), "decided_as_base": sum(1 for r in rows if r["passed"])}

        async def curve() -> dict[str, Any]:
            import tempfile

            from brain import config
            from brain.config import Policy

            with tempfile.TemporaryDirectory(prefix="bench-curve-") as workdir:
                rows = await learning_curve("d3", 3, Path(workdir), config.load(Policy, "policy"))
            return {"team_runs_first_to_last": f"{rows[0]['team_runs']} to {rows[-1]['team_runs']}", "same_decisions": all(r["decisions_equal_to_run_1"] for r in rows)}

        steps |= {"variants": variant_run, "learning_curve": curve}
    return steps


async def _conformance(kit: Any) -> list[Any]:
    import os

    import httpx

    from brain.api import Hub, create_app
    from brain.config import ModelsConfig, PartnersConfig, Policy
    from mocks.guardian.engine import MockGuardian
    from mocks.guardian.server import build_app
    from mocks.twin.engine import MockTwin
    from mocks.twin.server import build_server

    twin_secret, brain_secret = os.environ.get("TWIN_HMAC_SECRET"), os.environ.get("BRAIN_HMAC_SECRET")
    results = await kit.run_twin(build_server(MockTwin(twin_secret, brain_secret)), twin_secret, brain_secret=brain_secret, probe=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_app(MockGuardian(twin_secret))), base_url="http://guardian") as client:
        results += await kit.run_guardian(client, twin_secret)
    hub = Hub(PartnersConfig(), Policy(), ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}}), mocks="inproc")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        results += await kit.run_brain(client)
    return results


async def run(steps: dict[str, Step], root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"date": datetime.now(UTC).strftime("%Y-%m-%d"), "commit": _commit(root), "machine": f"{platform.machine()}, Python {platform.python_version()}", "results": {}, "failures": []}
    for name, step in steps.items():
        started = time.perf_counter()
        try:
            out["results"][name] = await step()
        except Exception as error:  # a failing step is a result, not a crash and never silence  # noqa: BLE001
            out["results"][name] = {"error": f"{type(error).__name__}: {error}"}
            out["failures"].append(name)
        out["results"][name]["_seconds"] = round(time.perf_counter() - started, 1) if isinstance(out["results"][name], dict) else None
    return out


def markdown(report: dict[str, Any]) -> str:
    lines = [f"# Bench, {report['date']}", "", f"Commit {report['commit']} on {report['machine']}.", "", "| Step | Result |", "| --- | --- |"]
    for name, value in report["results"].items():
        shown = {k: v for k, v in value.items() if k != "_seconds"}
        lines.append(f"| {name} | " + "; ".join(f"{k}: {v}" for k, v in shown.items()) + f" ({value.get('_seconds')} s) |")
    lines += ["", f"**{'FAILED: ' + ', '.join(report['failures']) if report['failures'] else 'Every step ran.'}**"]
    return "\n".join(lines) + "\n"
