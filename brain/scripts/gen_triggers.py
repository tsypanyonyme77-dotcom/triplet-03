"""Writes scenarios/triggers/bN.sh, one trigger script per Test Book scenario (Phase 1 rule R2: one command launches a scenario).

    uv run python scripts/gen_triggers.py

Each script is a single command: `./scenarios/triggers/d3.sh` runs the scenario and leaves its log in logs/.
Extra arguments pass through: `./scenarios/triggers/d3.sh --inproc --speed 0`.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scenarios" / "triggers"
OUT.mkdir(exist_ok=True)

for scenario in sorted((ROOT / "scenarios").glob("d*.json"), key=lambda p: int(p.stem[1:])):
    script = OUT / f"{scenario.stem}.sh"
    script.write_text(f'#!/usr/bin/env bash\n# Test Book scenario {scenario.stem}: one command, one log in logs/.\ncd "$(dirname "$0")/../.." && exec uv run brain scenario {scenario.stem} "$@"\n')
    script.chmod(0o755)
    print(f"wrote {script.relative_to(ROOT)}")
