"""Writes logs/canonical/bN.jsonl and bN.inputs.jsonl: one verified, repeatable run of every Test Book scenario.

    uv run python scripts/make_canonical.py [d3 d4 ...]

The runs are deterministic (see brain.clock), so rerunning gives the same bytes, and `brain replay logs/canonical/bN.inputs.jsonl`
reproduces them. They are sealed with the development secrets, so replay them with no `.env` loaded. A scenario that fails is not written.
"""

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

from brain import baseline
from brain.scenario import DEV_SECRETS, inproc_partners, load_scenario, run_scenario

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "logs" / "canonical"


async def one(scenario_id: str) -> bool:
    with tempfile.TemporaryDirectory() as folder:
        result = await run_scenario(load_scenario(scenario_id), inproc_partners(), models=baseline.MODELS, speed=0, timeout_s=60,
                                    log_dir=Path(folder), deterministic=True)
        if not result.passed:
            print(f"FAILED {scenario_id}: not written")
            return False
        shutil.copy(result.log_path, OUT / f"{scenario_id}.jsonl")
        shutil.copy(result.log_path.with_name(result.log_path.stem + ".inputs.jsonl"), OUT / f"{scenario_id}.inputs.jsonl")
    print(f"wrote logs/canonical/{scenario_id}.jsonl")
    return True


async def main(ids: list[str]) -> int:
    import os

    for name, value in DEV_SECRETS.items():
        os.environ[name] = value  # sealed with the development secrets whatever the environment holds
    OUT.mkdir(parents=True, exist_ok=True)
    ids = ids or [p.stem for p in sorted((ROOT / "scenarios").glob("d*.json"), key=lambda p: int(p.stem[1:]))]
    return 0 if all([await one(i) for i in ids]) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
