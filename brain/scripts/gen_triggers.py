"""Writes scenarios/triggers/bN.sh, one trigger script per Test Book scenario (Phase 1 rule R2: one command launches a scenario).

    uv run python scripts/gen_triggers.py

Each script is a single command: `./scenarios/triggers/t14.sh` runs the scenario and leaves its log in the root logs/ folder (logs/t14-<timestamp>.jsonl).
Extra arguments pass through: `./scenarios/triggers/t14.sh --inproc --speed 0`.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scenarios" / "triggers"
OUT.mkdir(exist_ok=True)

for scenario in sorted((ROOT / "scenarios").glob("t*.json"), key=lambda p: int(p.stem[1:])):
    script = OUT / f"{scenario.stem}.sh"
    script.write_text(f'#!/usr/bin/env bash\n# Test Book scenario {scenario.stem}: one command, one log in the repo root logs/ folder (LOG_DIR overrides).\ncd "$(dirname "$0")/../.." && LOG_DIR="${{LOG_DIR:-../logs}}" exec uv run brain scenario {scenario.stem} "$@"\n')
    script.chmod(0o755)
    print(f"wrote {script.relative_to(ROOT)}")
