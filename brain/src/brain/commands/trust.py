"""Commands for interoperability and security: onboarding a new Twin, conformance, the red team, tokens, and checking a log's seal."""

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
from brain.commands.common import _models, serve_partners
from brain.config import PartnersConfig, Policy
from brain.timeline import verify_chain


def cmd_onboard(args: argparse.Namespace) -> int:
    """Propose the `twin.type_aliases` and `twin.profiles` for a Twin that names things differently. Prints; never edits a file."""
    from brain import onboard

    if args.sample:
        data = json.loads(Path(args.sample).read_text())
        readings = data["readings"] if isinstance(data, dict) else data
    else:
        from mcp import Client

        async def fetch() -> list[dict[str, Any]]:
            async with Client(args.twin) as client:
                for _ in range(40):
                    page = json.loads((await client.call_tool("list_readings", {"cursor": 0, "limit": args.readings})).content[0].text)
                    if page["readings"]:
                        return page["readings"]
                    await asyncio.sleep(0.25)
            return []

        readings = asyncio.run(fetch())
    proposal = onboard.propose(readings[: args.readings])
    if args.yaml:
        print(proposal.yaml())
    else:
        for line in proposal.lines:
            print(f"{'REVIEW' if line['review'] else 'ok    '}  {line['confidence']:.2f}  {line['theirs']} -> {line['ours']}  ({line['evidence']})")
        for theirs in proposal.unmapped:
            print(f"UNMAPPED       {theirs}")
        print(f"\n{len(proposal.type_aliases)} types mapped, {len(proposal.unmapped)} unmapped. Nothing was written: edit config/partners.yaml (use --yaml for the lines).")
    return 0


def cmd_conformance(args: argparse.Namespace) -> int:
    """Check a Twin, a Guardian and a Brain against the contract. No arguments: the shipped mocks and this Brain, in process."""
    import httpx

    from brain import conformance as kit
    from brain.scenario import DEV_SECRETS

    root = str(config.home())
    if root not in sys.path:  # the stand-ins live in `mocks/`, next to `src/`
        sys.path.insert(0, root)
    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    twin_secret, brain_secret = os.environ.get(args.twin_secret_env), os.environ.get(args.brain_secret_env)
    headers = {"Authorization": f"Bearer {os.environ[args.token_env]}"} if args.token_env and os.environ.get(args.token_env) else {}

    async def run() -> list[kit.Result]:
        results: list[kit.Result] = []
        if args.twin or not (args.guardian or args.brain):
            if args.twin:
                results += await kit.run_twin(args.twin, twin_secret, brain_secret=brain_secret, probe=args.probe_actuators)
            else:
                from mocks.twin.engine import MockTwin
                from mocks.twin.server import build_server

                results += await kit.run_twin(build_server(MockTwin(twin_secret, brain_secret)), twin_secret, brain_secret=brain_secret, probe=True)
        if args.guardian or not (args.twin or args.brain):
            if args.guardian:
                async with httpx.AsyncClient(base_url=args.guardian) as client:
                    results += await kit.run_guardian(client, twin_secret)
            else:
                from mocks.guardian.engine import MockGuardian
                from mocks.guardian.server import build_app

                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_app(MockGuardian(twin_secret))), base_url="http://guardian") as client:
                    results += await kit.run_guardian(client, twin_secret)
        if args.brain or not (args.twin or args.guardian):
            if args.brain:
                async with httpx.AsyncClient(base_url=args.brain) as client:
                    results += await kit.run_brain(client, headers)
            else:
                from brain.api import Hub, create_app

                hub = Hub(PartnersConfig(), config.load(Policy, "policy"), _models(args), mocks="inproc")
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
                    results += await kit.run_brain(client)
        return results

    results = asyncio.run(run())
    print(kit.as_json(results) if args.json else kit.table(results))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(kit.markdown(datetime.now(UTC).strftime("%Y-%m-%d"), results))
    return 1 if kit.summary(results)[2] else 0


def cmd_redteam(args: argparse.Namespace) -> int:
    """Attack the Brain 22 ways. No URL: a Brain in process with tokens required. Exit 1 if any attack got through."""
    import httpx

    from brain import conformance as kit
    from brain import redteam

    async def run() -> list[kit.Result]:
        if not args.brain:
            return await redteam.run_in_process()
        tokens = {name: os.environ[env] for name, env in redteam.TOKEN_ENVS.items() if os.environ.get(env)}
        async with httpx.AsyncClient(base_url=args.brain) as client:
            return await redteam.run(client, tokens)

    results = asyncio.run(run())
    print(kit.as_json(results) if args.json else kit.table(results))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(kit.markdown(datetime.now(UTC).strftime("%Y-%m-%d"), results))
    return 1 if kit.summary(results)[2] else 0


def cmd_security_check(args: argparse.Namespace) -> int:
    """Run the security tests: the invariants (only the gate actuates, no dangerous calls, constant-time secret checks) and the API's edge."""
    import subprocess

    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_security_invariants.py", "tests/test_security.py", "tests/test_approval.py"], cwd=config.home(), check=False)
    print("security-check: " + ("every invariant holds" if result.returncode == 0 else "FAILED, see above"))
    return result.returncode


def cmd_security_report(args: argparse.Namespace) -> int:
    """Run the evidence for every threat in docs/SECURITY.md and write docs/security/<date>.md. Exit 1 if any threat's evidence fails."""
    from brain import redteam, securityreport

    root = config.home()
    threats = securityreport.parse((root / "docs/SECURITY.md").read_text())
    tests = securityreport.run_tests(sorted({f for t in threats for f in t.tests}), root)
    attacks = {r.id[1:]: r.status for r in asyncio.run(redteam.run_in_process())}
    securityreport.assess(threats, tests, attacks)
    text = securityreport.markdown(datetime.now(UTC).strftime("%Y-%m-%d"), threats)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
    return 1 if any(t.status == "fail" for t in threats) else 0


def cmd_token(args: argparse.Namespace) -> int:
    """Mint a short-lived token, or revoke one by id. The static tokens in the environment keep working."""
    from brain.security import mint_token

    security = PartnersConfig().security if not getattr(args, "config", None) else serve_partners(args).security
    if args.revoke:
        path = Path(security.revocations_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as file:
            file.write(args.revoke + "\n")
        print(f"revoked {args.revoke}")
        return 0
    key = os.environ.get(security.token_key_env)
    if not key:
        print(f"error: set {security.token_key_env} (the key that signs tokens)", file=sys.stderr)
        return 2
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    ttl = int(args.ttl[:-1]) * units[args.ttl[-1]] if args.ttl[-1] in units else int(args.ttl)
    token, jti = mint_token(key, args.sub, args.scope.split(","), ttl)
    print(f"{token}\n(id {jti}; expires in {args.ttl}; revoke with: brain token --revoke {jti})", file=sys.stderr)
    print(token)
    return 0


def cmd_audit_verify(args: argparse.Namespace) -> int:
    from brain.timeline import verify_head

    ok, message = verify_chain(Path(args.log))
    print(f"{'OK' if ok else 'BROKEN'}: {message}")
    status, detail = verify_head(Path(args.log), os.environ.get("BRAIN_HMAC_SECRET"))
    print(f"head {status}: {detail}")
    return 0 if ok and status in ("ok", "missing") else 1
