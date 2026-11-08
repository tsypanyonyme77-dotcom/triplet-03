#!/usr/bin/env python3
"""Runs one Test Book scenario on a running city and waits for its log (standard library only).

    python3 scenarios/trigger.py t1 [--brain auto|operator] [--seed N] [--speed X]

Exit code 0 when the scenario passes. The Twin writes logs/<id>-<UTC time>.log.
TWIN_URL (default http://localhost:8000) and TWIN_OPERATOR_KEY say which Twin and how to reach it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

TWIN_URL = os.environ.get("TWIN_URL", "http://localhost:8000").rstrip("/")
OPERATOR_KEY = os.environ.get("TWIN_OPERATOR_KEY", "dev-only-operator-key")
POLL_S = 1.0
GIVE_UP_S = 3600.0


def call(path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(f"{TWIN_URL}{path}", data=data, headers={"Content-Type": "application/json", "X-Operator-Key": OPERATOR_KEY})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def run(scenario_id: str, brain: str = "auto", seed: int | None = None, speed: float | None = None) -> int:
    body = {"brain": brain, **({"seed": seed} if seed is not None else {}), **({"speed": speed} if speed is not None else {})}
    try:
        started = call(f"/scenarios/{scenario_id}/run", body)
    except urllib.error.HTTPError as exc:
        print(f"the Twin refused: {exc.code} {exc.read().decode()[:300]}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"cannot reach the Twin at {TWIN_URL}: {exc}. Is `docker compose up` running?", file=sys.stderr)
        return 2
    print(f"{scenario_id} started at {started['started_at']}: {started['name']}, watch it on the timeline")
    deadline = time.monotonic() + GIVE_UP_S
    while time.monotonic() < deadline:
        time.sleep(POLL_S)
        status = call("/scenarios")
        last = status["last"]
        if status["current"] is None and last and last["id"] == scenario_id and last["finished_at"] >= started["started_at"]:
            for check in last.get("checks", []):
                print(f"  {'seen   ' if check['seen'] else 'MISSING'} {check['layer']}: {check['kind']} ({check['meaning']})")
            print(f"{scenario_id}: {last['result']}" + (f", logs/{last['log']}" if last.get("log") else "") + (f", {last['error']}" if last.get("error") else ""))
            return 0 if last["result"] == "PASS" else 1
    print(f"gave up waiting for {scenario_id}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one Test Book scenario and wait for its log.")
    parser.add_argument("scenario", help="t1, t2, ...")
    parser.add_argument("--brain", choices=["auto", "operator"], default="auto", help="who decides in a mock City Brain")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--speed", type=float)
    args = parser.parse_args()
    return run(args.scenario, args.brain, args.seed, args.speed)


if __name__ == "__main__":
    raise SystemExit(main())
