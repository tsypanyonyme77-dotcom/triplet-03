"""Commands that run the Brain: a scenario, the live loop, the screen, a replay, a repeatability check, and the schemas."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from brain import config, contracts
from brain.adapters import open_twin
from brain.adapters.tls import guardian_client, uvicorn_options
from brain.backends import open_backends
from brain.commands.common import _log_dir, _models, _warn, serve_partners
from brain.config import PartnersConfig, Policy, TlsConfig
from brain.persistence import live_session
from brain.timeline import ConsoleSink, JsonlSink, Timeline

SCHEMA_MODELS = [
    contracts.Approval,
    contracts.SensorReading,
    contracts.TrustVerdict,
    contracts.ActuatorCall,
    contracts.ActuatorResult,
    contracts.DispatchUnitParams,
    contracts.BroadcastAlertParams,
    contracts.RecallUnitParams,
    contracts.SetSignalPhaseParams,
    contracts.SetValveStateParams,
    contracts.SetGridConnectionParams,
    contracts.CitizenActivity,
    contracts.CctvAnomaly,
    contracts.Gunshot,
    contracts.EmergencyCall,
    contracts.UnitStatus,
    contracts.TrafficCamera,
    contracts.WaterLevel,
    contracts.PowerLoad,
    contracts.AirQuality,
    contracts.TimelineEvent,
]


def cmd_scenario(args: argparse.Namespace) -> int:
    from brain import scenario as runner

    if args.deterministic and not args.inproc:
        print("error: --deterministic needs --inproc: spawned mock partners run in their own processes with the real clock", file=sys.stderr)
        return 2
    partners = config.load(PartnersConfig, "partners", args.config)
    policy = config.load(Policy, "policy")
    models = _models(args)
    for name, value in runner.DEV_SECRETS.items():
        if name not in os.environ:
            os.environ[name] = value
            print(f"note: {name} is not set, using the development default", file=sys.stderr)

    try:
        definition = runner.load_scenario(args.id)
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.inproc:
        context = runner.inproc_partners()
    elif args.no_spawn:
        context = runner.running_partners(partners)
    else:
        context = runner.spawned_partners(partners)

    print(f"scenario {definition['id']}: {definition.get('name', '')}")
    if args.graph:
        partners.graph.backend = args.graph

    async def play() -> runner.ScenarioResult:
        run_id = f"{definition['id']}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        async with open_backends(partners.graph, models, run_id, _warn) as backends:
            if backends.note:
                _warn(backends.note)
            return await runner.run_scenario(
                definition, context, partners=partners, policy=policy, models=models, speed=args.speed, deterministic=args.deterministic,
                store=backends.store, kb=backends.kb,
                log_dir=_log_dir(partners), console=not args.quiet, timeout_s=args.timeout,
            )

    result = asyncio.run(play())
    print()
    for check in result.checks:
        print(f"  {'PASS' if check.passed else 'FAIL'}  {check.name}" + (f"  ({check.detail})" if not check.passed else ""))
    print(f"\n{'PASSED' if result.passed else 'FAILED'}  log: {result.log_path}")
    return 0 if result.passed else 1


def cmd_run(args: argparse.Namespace) -> int:

    from brain.adapters import open_guardian, with_gateway
    from brain.runtime import BrainService

    partners = config.load(PartnersConfig, "partners", args.config)
    policy = config.load(Policy, "policy")
    models = _models(args)
    if config.secret(partners.twin.hmac_secret_env) is None:
        print(f"warning: {partners.twin.hmac_secret_env} is not set; reading signatures will NOT be verified", file=sys.stderr)

    if args.graph:
        partners.graph.backend = args.graph

    async def main() -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        brain = partners.brain
        state, log_path, resumed = live_session(brain.state_file, brain.state_max_age_s, config.home(), _log_dir(partners), args.fresh)
        if resumed:
            print(f"note: continuing the session saved in {state.path} (start with --fresh to forget it)", file=sys.stderr)
        log = JsonlSink(log_path, resume=resumed)
        timeline = Timeline([log, ConsoleSink(verbose=args.verbose)])
        async with open_backends(partners.graph, models, f"live-{stamp}", _warn) as backends:
            if backends.note:
                _warn(backends.note)
            async with guardian_client(partners.guardian.url, partners.guardian.tls) as client:
                async with open_twin(partners.twin) as twin:
                    guardian = open_guardian(partners.guardian, client)
                    service = BrainService(partners, policy, with_gateway(twin, guardian, partners.guardian), guardian, timeline, models,
                                           store=backends.store, kb=backends.kb, state=state)
                    await service.start()
                    try:
                        await service.run()
                    finally:
                        log.close()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from brain import scenario as runner
    from brain.api import Hub, create_app

    partners = serve_partners(args)
    if partners.security.require == "auto" and args.host not in ("127.0.0.1", "::1", "localhost"):
        partners.security.require = "always"  # off loopback, tokens are on
    if partners.security.require == "always":
        from brain.security import Security

        if not Security(partners.security).tokens():
            print(f"error: the server listens on {args.host} with tokens required, but no token is set: set BRAIN_TOKEN_READ and the others (see config/partners.yaml, security)", file=sys.stderr)
            return 2
    mocks = "none" if args.live else args.mocks
    if mocks != "none":
        for name, value in runner.DEV_SECRETS.items():
            if name not in os.environ:
                os.environ[name] = value
                print(f"note: {name} is not set, using the development default", file=sys.stderr)
    listener = TlsConfig(ca=args.tls_client_ca, cert=args.tls_cert, key=args.tls_key) if args.tls_cert else partners.security.tls
    if not (listener and listener.cert) and args.host not in ("127.0.0.1", "::1", "localhost"):
        print(f"warning: the server listens on {args.host} over plain HTTP; use --tls-cert and --tls-key (scripts/make_certs.sh) unless this network is private", file=sys.stderr)
    hub = Hub(partners, config.load(Policy, "policy"), _models(args), mocks=mocks, log_dir=_log_dir(partners), fresh=args.fresh)
    app = create_app(hub)

    async def main() -> None:
        server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="warning", **uvicorn_options(listener)))
        live = asyncio.create_task(hub.run_live()) if mocks == "none" else None
        warm = asyncio.create_task(_warm(hub)) if mocks == "inproc" else None  # keep a reference: a bare task can be collected
        print(f"City Brain on http://{args.host}:{args.port}  ({'live partners' if live else mocks + ' mocks; start a scenario from the screen'})")
        try:
            await server.serve()
        finally:
            if live is not None:
                live.cancel()
            if warm is not None:
                warm.cancel()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    return 0


async def _warm(hub) -> None:  # noqa: ANN001 - the Hub is imported inside cmd_serve
    """Play the calm day once, unseen, so the first click on the screen does not wait for the playbook to be embedded."""
    from brain import scenario as runner

    try:
        await runner.run_scenario(runner.load_scenario("t12"), runner.inproc_partners(), partners=hub.partners, policy=hub.policy, models=hub.models, speed=0, timeout_s=60)
    except Exception as error:  # noqa: BLE001 - a failed warm-up only means the first click is slower
        print(f"note: warm-up did not finish ({type(error).__name__}: {error})", file=sys.stderr)


def cmd_replay(args: argparse.Namespace) -> int:
    from brain import replay as replaying
    from brain.timeline import read_log

    path = Path(args.journal)
    policy = config.load(Policy, "policy") if args.current_config else None
    try:
        events = asyncio.run(replaying.replay(path, policy=policy, allow_config_change=args.allow_config_change))
    except replaying.ReplayRefused as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    timeline = Path(args.timeline) if args.timeline else path.with_name(path.name.replace(".inputs.jsonl", ".jsonl"))
    recorded = [{k: v for k, v in record.items() if k not in ("hash", "prevhash")} for record in read_log(timeline)]
    difference = replaying.compare(events, recorded)
    if not difference.same:
        print(f"replay differs from {timeline.name}: first difference {difference.first_difference}")
        return 1
    print(f"replay matches {timeline.name}: {len(events)} events, decisions and stream identical")
    return 0


def cmd_repro(args: argparse.Namespace) -> int:
    from brain import repro

    rows, _ = asyncio.run(repro.report(args.id, args.runs, args.processes, deterministic=args.deterministic))
    if args.json:
        print(json.dumps([{"level": r.name, "distinct": r.distinct, "first_difference": r.first_difference} for r in rows], indent=2))
    else:
        print(repro.format_table(args.id, args.runs, rows))
    return 0 if rows[0].identical else 1  # a changed decision is a bug; a changed id or time is a finding


def cmd_env(args: argparse.Namespace) -> int:
    from brain.envprint import fingerprint_env

    print(json.dumps(fingerprint_env(), indent=2))
    return 0


def cmd_export_schemas(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else config.home() / "contracts" / "schemas"
    out.mkdir(parents=True, exist_ok=True)
    for model in SCHEMA_MODELS:
        path = out / f"{model.__name__}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
        print(f"wrote {path}")
    return 0


def cmd_rehearse(args: argparse.Namespace) -> int:
    from brain.rehearse import rehearse

    out = Path(args.out) if args.out else config.home() / "docs" / "rehearsal"
    report = asyncio.run(rehearse(out, quick=args.quick, screens=not args.no_screens))
    for step in report.steps:
        print(f"  {'PASS' if step.passed else 'FAIL'}  {step.name}: {step.detail}")
    print(f"\n{'PASSED' if report.passed else 'FAILED'} in {report.seconds:.0f} s. report: {out}")
    return 0 if report.passed else 1


def cmd_llm_check(args: argparse.Namespace) -> int:
    """Is the hosted model reachable, is the key good and is there quota left? One one-token call per distinct Groq model. Exit 1 if any fails."""
    from brain.llm_health import LLMHealth, probe_into

    key = os.environ.get("GROQ_API_KEY", "")
    specs = sorted({spec.removeprefix("groq:") for spec in _models(args).roles.values() if spec.startswith("groq:")})
    if not specs or not key:
        print("no Groq model is configured, or GROQ_API_KEY is not set (run with --env-file .env)")
        return 1

    async def check() -> int:
        failed = 0
        for model in specs:
            health = LLMHealth()
            answer = await probe_into(health, model, key)
            left = f"; tokens left this minute: {answer['remaining_tokens']}, requests left today: {answer['remaining_requests']}" if answer["ok"] else ""
            print(f"{model}: {'ok' if answer['ok'] else 'FAILED, ' + str(answer.get('why') or answer.get('error'))}{left}")
            failed += not answer["ok"]
        return 1 if failed else 0

    return asyncio.run(check())
