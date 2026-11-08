"""Scenario runner: one trigger, one log file, a pass/fail verdict (requirement R2).

Runs the real Brain against the mock Twin and mock Guardian, either in-process or as
separate servers over MCP and REST.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import socket
import subprocess
import sys
from collections import Counter
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from brain import clock, config
from brain.adapters import HttpTwinAdapter, McpTwinAdapter, MqttTwinAdapter, RestGuardianAdapter
from brain.citygraph import MemoryGraphStore
from brain.config import ModelsConfig, MqttConfig, PartnersConfig, Policy, fingerprint
from brain.departments.team import LLMCrew
from brain.envprint import fingerprint_env
from brain.journal import JournalingGuardian, JournalingTwin, JournalWriter
from brain.knowledge import KnowledgeBase
from brain.runtime import BrainService
from brain.timeline import ConsoleSink, JsonlSink, MemorySink, Timeline

DEV_SECRETS = {"TWIN_HMAC_SECRET": "dev-only-twin-secret", "BRAIN_HMAC_SECRET": "dev-only-brain-secret", "BRAIN_APPROVAL_SECRET": "dev-only-approval-secret"}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ScenarioResult:
    scenario_id: str
    log_path: Path | None
    sink: MemorySink
    actuator_calls: list[dict[str, Any]]
    checks: list[Check] = field(default_factory=list)
    attacks: dict[str, Any] = field(default_factory=dict)  # what the scenario's attacks got back (pushes: status and error per attempt)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


def expand_streams(scenario: dict[str, Any]) -> dict[str, Any]:
    """Replace the scenario's `streams` with the events they generate, merged into `events` by time.

    A stream is a sensor reporting at a steady interval around a base value, so a calm day takes a few
    lines instead of hundreds of hand-written events. The same seed always gives the same noise.
    """
    expanded = {key: value for key, value in scenario.items() if key != "streams"}
    if not scenario.get("streams"):
        return expanded
    generated = []
    for stream in scenario.get("streams", []):
        noise_source = random.Random(stream.get("seed", 0))
        noise, clamp = stream.get("noise", {}), stream.get("clamp", {})
        for at_ms in range(stream["from_ms"], stream["to_ms"], stream["every_ms"]):
            value = {}
            for field_name, base in stream["base"].items():
                if isinstance(base, bool) or not isinstance(base, int | float):
                    value[field_name] = base
                    continue
                sample = noise_source.gauss(base, noise[field_name]) if field_name in noise else base
                if field_name in clamp:
                    sample = min(max(sample, clamp[field_name][0]), clamp[field_name][1])
                value[field_name] = round(sample) if isinstance(base, int) else round(sample, 4)
            generated.append({"at_ms": at_ms, "sensor_id": stream["sensor_id"], "type": stream["type"],
                              "zone_id": stream["zone_id"], "value": value})
    # Events without an `at_ms` are follow-ups the Twin schedules itself; they sort last and stay as written.
    expanded["events"] = sorted([*generated, *scenario.get("events", [])], key=lambda event: event.get("at_ms", float("inf")))
    return expanded


def _deep_merge(base: dict[str, Any], own: dict[str, Any]) -> dict[str, Any]:
    """`own` laid over `base`: dictionaries merge all the way down (so a scenario adds to its base's `expect`), everything else is replaced."""
    return {**base, **{key: _deep_merge(base[key], value) if isinstance(value, dict) and isinstance(base.get(key), dict) else value for key, value in own.items()}}


def load_raw_scenario(scenario_id: str, scenarios_dir: Path | None = None) -> dict[str, Any]:
    """A scenario as written (streams not yet expanded into events), with its topology file read in."""
    folder = scenarios_dir or config.home() / "scenarios"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", scenario_id):  # an id is a plain name, never a path
        raise FileNotFoundError(f"no scenario {scenario_id!r}: a scenario id is letters, digits, - and _")
    path = folder / f"{scenario_id}.json"
    if not path.exists():
        known = sorted(p.stem for p in folder.glob("*.json"))
        raise FileNotFoundError(f"no scenario {scenario_id!r} in {folder} (known: {known})")
    scenario = json.loads(path.read_text())
    if "same_as" in scenario:  # the same city under another condition (a transport, a fault): everything not restated is the base's
        scenario = _deep_merge(load_raw_scenario(scenario["same_as"], scenarios_dir), {k: v for k, v in scenario.items() if k != "same_as"})
    if isinstance(scenario.get("topology"), str):
        scenario["topology"] = json.loads((folder / scenario["topology"]).read_text())
    return scenario


def load_scenario(scenario_id: str, scenarios_dir: Path | None = None) -> dict[str, Any]:
    return expand_streams(load_raw_scenario(scenario_id, scenarios_dir))


def _import_mocks():
    root = str(config.home())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from mocks.guardian.engine import MockGuardian
        from mocks.guardian.server import build_app
        from mocks.twin.engine import MockTwin
        from mocks.twin.server import build_server
    except ModuleNotFoundError as error:
        raise RuntimeError(f"cannot import the mocks from {root}; run from the brain/ folder or set BRAIN_HOME") from error
    return MockTwin, build_server, MockGuardian, build_app


@dataclass
class MqttTarget:
    """A Twin whose readings come by broker and whose actions go over HTTP: what `inproc_partners(transport="mqtt")` hands the runner."""

    http: httpx.AsyncClient
    broker: Any  # mocks.twin.mqtt_publisher.InProcessBroker


@asynccontextmanager
async def _inproc_partners(disabled_actuators: frozenset[str], transport: str) -> AsyncIterator[tuple[Any, httpx.AsyncClient]]:
    """Mock Twin and Guardian in this process, still spoken to over MCP and HTTP semantics.

    `disabled_actuators` imitates a Twin that cannot expose some actuators. `transport` is `mcp`, `http`, or `mqtt` (readings through an
    in-process broker, everything else over HTTP).
    """
    MockTwin, build_server, MockGuardian, build_app = _import_mocks()
    twin = MockTwin(os.environ.get("TWIN_HMAC_SECRET"), os.environ.get("BRAIN_HMAC_SECRET"))
    app = build_app(MockGuardian(os.environ.get("TWIN_HMAC_SECRET")))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://guardian") as client:
        if transport == "mqtt":
            from mocks.twin.http_server import build_app as build_http_app
            from mocks.twin.mqtt_publisher import InProcessBroker, drive

            broker, publishers = InProcessBroker(), []

            async def page(cursor: int) -> dict[str, Any]:
                return twin.list_readings(cursor, 200)

            def start_publisher() -> None:
                # The publisher starts when the Brain has subscribed: a broker keeps nothing for a late subscriber.
                if not publishers:
                    publishers.append(asyncio.get_running_loop().create_task(drive(page, broker.publish)))

            broker.on_subscribe = start_publisher
            try:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_http_app(twin, disabled_actuators)), base_url="http://twin") as twin_client:
                    yield MqttTarget(twin_client, broker), client
            finally:
                for task in publishers:
                    task.cancel()
            return
        if transport == "http":  # the same mock Twin, spoken to over plain HTTP
            from mocks.twin.http_server import build_app as build_http_app

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=build_http_app(twin, disabled_actuators)), base_url="http://twin") as twin_client:
                yield twin_client, client
            return
        yield build_server(twin, disabled_actuators), client


class InprocPartners:
    """`inproc_partners(...)`: use it as `async with`. Left without a transport, it takes the one the scenario names (`transport` in the file), else MCP."""

    def __init__(self, disabled_actuators: frozenset[str], transport: str | None) -> None:
        self.disabled_actuators, self.transport = disabled_actuators, transport
        self._open: Any = None

    async def __aenter__(self) -> tuple[Any, httpx.AsyncClient]:
        self._open = _inproc_partners(self.disabled_actuators, self.transport or "mcp")
        return await self._open.__aenter__()

    async def __aexit__(self, *exc: object) -> bool | None:
        return await self._open.__aexit__(*exc)


def inproc_partners(disabled_actuators: frozenset[str] = frozenset(), transport: str | None = None) -> InprocPartners:
    return InprocPartners(disabled_actuators, transport)


async def _wait_for_port(host: str, port: int, timeout_s: float = 15.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError(f"mock server on {host}:{port} did not start within {timeout_s}s") from None
            await asyncio.sleep(0.1)


@asynccontextmanager
async def spawned_partners(partners: PartnersConfig) -> AsyncIterator[tuple[str, httpx.AsyncClient]]:
    """Start the two mock servers as subprocesses on the configured addresses."""
    twin_url, guardian_url = urlparse(partners.twin.url), urlparse(partners.guardian.url)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(config.home()), os.environ.get("PYTHONPATH")]))}
    processes = [
        subprocess.Popen([sys.executable, "-m", f"mocks.{name}", "--host", url.hostname, "--port", str(url.port)],
                         cwd=config.home(), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for name, url in (("twin", twin_url), ("guardian", guardian_url))
    ]
    try:
        await _wait_for_port(twin_url.hostname, twin_url.port)
        await _wait_for_port(guardian_url.hostname, guardian_url.port)
        async with httpx.AsyncClient(base_url=partners.guardian.url) as client:
            yield partners.twin.url, client
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


@asynccontextmanager
async def running_partners(partners: PartnersConfig) -> AsyncIterator[tuple[str, httpx.AsyncClient]]:
    """Mock servers that are already running (for example under docker compose)."""
    async with httpx.AsyncClient(base_url=partners.guardian.url) as client:
        yield partners.twin.url, client


def _overlay(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in changes.items():
        merged[key] = _overlay(base[key], value) if isinstance(value, dict) and isinstance(base.get(key), dict) else value
    return merged


def _is_subsequence(needles: list[str], haystack: list[str]) -> bool:
    remaining = iter(haystack)
    return all(needle in remaining for needle in needles)


# The events of one team deliberation: absent when a plan sleep compiled took its place.
TEAM_EVENTS = {"brain.deliberation.started", "brain.deliberation.finished", "brain.case.reviewed", "brain.options.prepared",
               "brain.plan.verified", "brain.plan.rejected"}


def evaluate(expect: dict[str, Any], sink: MemorySink, actuator_calls: list[dict[str, Any]], scripted_team: bool = True, attacks: dict[str, Any] | None = None) -> list[Check]:
    """Check a run against the scenario's expectations.

    The top level is what must hold whoever deliberates (the reflex tier's behaviour).
    `scripted_team` adds what the scripted department team is known to decide; an LLM
    team is free to plan differently, within the gate.
    """
    checks: list[Check] = []
    types = sink.types()
    extra = expect.get("scripted_team", {}) if scripted_team else {}

    def matches(call: dict[str, Any], want: dict[str, Any]) -> bool:
        return all((call.get("actuator_id") if key == "actuator_id" else call["params"].get(key)) == value for key, value in want.items())

    dispatched = [c["call"] for c in actuator_calls if c["result"].get("status") == "dispatched"]
    wanted = [*expect.get("dispatched", []), *extra.get("dispatched", [])]
    present = all(any(matches(call, want) for call in dispatched) for want in wanted)
    exact = len(dispatched) == len(wanted) if scripted_team else len(dispatched) >= len(wanted)
    summary = [call["params"] for call in dispatched]
    checks.append(Check("twin received the expected dispatches", present and exact, f"expected {wanted}, twin dispatched {summary}"))
    if "dispatched_from" in expect:
        pursuits = sorted(call["actuator_id"] for call in dispatched if call["params"].get("mode") == "pursuit")
        checks.append(Check("the pursuit comes from the expected station", pursuits == sorted(expect["dispatched_from"]), f"got {pursuits}"))
    for unwanted in expect.get("never_dispatched", []):
        hits = [call["params"] for call in dispatched if matches(call, unwanted)]
        checks.append(Check(f"nothing dispatched matching {unwanted}", not hits, f"twin dispatched {hits}"))
    if "dispatch_modes_in_order" in expect:
        sent = [call["params"].get("mode") or "respond" for call in dispatched]
        checks.append(Check(f"dispatched in order: {' -> '.join(expect['dispatch_modes_in_order'])}",
                            _is_subsequence(expect["dispatch_modes_in_order"], sent), f"got {sent}"))
    for want in expect.get("actuated", []):
        hits = [c for c in actuator_calls
                if c["call"]["action"] == want["action"] and matches(c["call"], want.get("params", {}))
                and c["result"].get("status") != "rejected"]
        checks.append(Check(f"twin received the expected actuator call: {want['action']} {want.get('params', {})}", bool(hits),
                            f"twin received {[(c['call']['action'], c['result'].get('status')) for c in actuator_calls]}"))
    unreferenced = [c["call"] for c in actuator_calls if not c["call"].get("trust_ref")]
    checks.append(Check("every actuator call carries a trust_ref", not unreferenced, f"{len(unreferenced)} without"))
    for key, name in (("recalled", "units recalled by the Brain"),):
        if key in expect or key in extra:
            wanted_count = extra.get(key, expect.get(key))
            count = sum(1 for c in actuator_calls if c["result"].get("status") == "recalled")
            checks.append(Check(f"{name}: {wanted_count}", count == wanted_count, f"twin recalled {count}"))
    if "blocked" in expect or "blocked" in extra:
        wanted_blocks = sorted([*expect.get("blocked", []), *extra.get("blocked", [])])
        seen = sorted(e.data.get("check", "") for e in sink.of("brain.action.blocked"))
        checks.append(Check(f"refusals and their reasons: {', '.join(wanted_blocks) or 'none'}", seen == wanted_blocks, f"got {seen}"))

    for chain in [*expect.get("events_in_order", []), *extra.get("events_in_order", [])]:
        name = f"in order: {' -> '.join(e.removeprefix('brain.') for e in chain)}"
        if "brain.plan.compiled" in types and TEAM_EVENTS.intersection(chain):
            # A learned plan replaced the team run these events describe; the decisions it produced are still checked above.
            checks.append(Check(name, True, "skipped: a learned plan replaced the team run"))
            continue
        checks.append(Check(name, _is_subsequence(chain, types)))
    for forbidden in [*expect.get("forbidden_events", []), *extra.get("forbidden_events", [])]:
        count = types.count(forbidden)
        checks.append(Check(f"no {forbidden}", count == 0, f"seen {count} time(s)"))
    if "rejected" in expect:
        seen = Counter(e.data.get("code") for e in sink.of("brain.reading.rejected"))
        checks.append(Check(f"readings refused, by reason: {expect['rejected']}", dict(seen) == expect["rejected"], f"got {dict(seen)}"))
    if "absent_from_actions" in expect:
        sent = json.dumps([c["call"] for c in actuator_calls])
        found = [text for text in expect["absent_from_actions"] if text in sent]
        checks.append(Check("none of the injected text is in any action sent", not found, f"found {found}"))
    if "absent_from_events" in expect:
        log = " ".join(json.dumps(e.model_dump(mode="json")) for e in sink.events)
        found = [text for text in expect["absent_from_events"] if text in log]
        checks.append(Check("none of the injected text is anywhere in the log", not found, f"found {found}"))
    if "pushes" in expect:
        got = [{"type": p["type"], "status": p["status"], "error": p.get("error")} for p in (attacks or {}).get("pushes", [])]
        checks.append(Check("each pushed event met its refusal, in order", got == expect["pushes"], f"got {got}"))
        leaked = (attacks or {}).get("leaked", [])
        checks.append(Check("no pushed brain.* event reached the stream a screen reads", not leaked, f"leaked {leaked}"))
    for event_type, wanted_count in {**expect.get("event_counts", {}), **extra.get("event_counts", {})}.items():
        count = types.count(event_type)
        checks.append(Check(f"{event_type} x{wanted_count}", count == wanted_count, f"seen {count} time(s)"))
    return checks


def _dates(value: Any) -> Any:
    """`@today` and `@yesterday` in a scenario's settings mean the run's own date, so a key that expires 'today' does so whenever the scenario runs."""
    today = clock.current().now().date()
    if isinstance(value, str):
        return {"@today": today.isoformat(), "@yesterday": (today - timedelta(days=1)).isoformat()}.get(value, value)
    if isinstance(value, dict):
        return {k: _dates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dates(v) for v in value]
    return value


@contextmanager
def scenario_env(values: dict[str, str]) -> Iterator[None]:
    """Development values a scenario needs in the environment for its run only (for example the keys of a rotation), restored after."""
    before = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, old in before.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


async def _push_attacks(pushes: list[dict[str, Any]], service: BrainService, partners: PartnersConfig, policy: Policy, models: ModelsConfig | None,
                        out: dict[str, Any]) -> None:
    """Push forged events at the Brain's own API while it runs, and note what came back and whether any of it reached the stream a screen reads.

    The API is the real one (`create_app`), in process, with the Brain's own timeline: a refusal is an event in the log like any other.
    """
    from brain.api import Hub, create_app

    quiet = partners.model_copy(deep=True)
    quiet.mcp.enabled = False
    hub = Hub(quiet, policy, models or ModelsConfig(), mocks="none")
    hub.service = service
    service.timeline.sinks.append(hub.broadcaster)  # the screen's stream sees the Brain's events and whatever the API lets through
    out["pushes"], out["leaked"] = [], []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        for push in pushes:
            await asyncio.sleep(0)  # between readings, as an attacker would
            response = await client.post("/api/events", json={"type": push["type"], "source": push.get("source", "twin"), "subject": push.get("subject"), "data": push.get("data", {})})
            detail = response.json().get("detail") if response.status_code >= 400 else None
            error = detail.get("error") if isinstance(detail, dict) else ("source_reserved" if response.status_code == 422 else None)
            out["pushes"].append({"type": push["type"], "status": response.status_code, "error": error})
    out["leaked"] = [r["type"] for r in hub.broadcaster.buffer if r.get("pushed") and str(r.get("type", "")).startswith("brain.")]


# The fixed start of a deterministic run: a Thursday long before any real run, so no log is mistaken for a live one.
DETERMINISTIC_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


async def run_scenario(scenario: dict[str, Any], partners_context: Any, *, deterministic: bool = False, **options: Any) -> ScenarioResult:
    """Run one scenario. With `deterministic`, the run uses a fixed epoch and numbered ids (see `brain.clock`), so two runs of one input give the same bytes."""
    with scenario_env(scenario.get("env", {})), clock.use(clock.DeterministicClock(DETERMINISTIC_EPOCH)) if deterministic else nullcontext():
        return await _run_scenario(scenario, partners_context, **options)


async def _run_scenario(
    scenario: dict[str, Any],
    partners_context: Any,
    *,
    partners: PartnersConfig | None = None,
    policy: Policy | None = None,
    models: ModelsConfig | None = None,
    llm_crew: LLMCrew | None = None,
    llm_health: Any = None,
    store: MemoryGraphStore | None = None,
    kb: KnowledgeBase | None = None,
    extra_sinks: list[Any] | None = None,
    on_service: Any = None,
    speed: float = 1.0,
    log_dir: Path | None = None,
    console: bool = False,
    timeout_s: float = 60.0,
) -> ScenarioResult:
    """Run one scenario. `partners_context` yields (twin target, guardian http client).

    A scenario may carry a `policy` section; it is laid over the configured policy for that run
    only, for behaviours a normal day never reaches (the action budget, for one).
    """
    partners, policy = partners or PartnersConfig(), policy or Policy()
    if isinstance(partners_context, InprocPartners) and partners_context.transport is None:
        partners_context.transport = scenario.get("transport")
    if scenario.get("policy"):
        policy = Policy.model_validate(_overlay(policy.model_dump(), scenario["policy"]))
    if scenario.get("partners"):  # a scenario about the Brain's own settings (a renamed Twin, a rotated key) says so here
        partners = PartnersConfig.model_validate(_overlay(partners.model_dump(mode="json"), _dates(scenario["partners"])))
    faults = scenario.get("faults", {})
    if "twin" in faults and "retry_s" in faults["twin"]:
        partners = partners.model_copy(deep=True)
        partners.twin.retry_s = faults["twin"]["retry_s"]
    if "knowledge" in faults and kb is None:
        from brain.faults import failing_knowledge
        from brain.knowledge.embedding import make_embedder

        embedder, _ = make_embedder((models or ModelsConfig()).embeddings.provider, (models or ModelsConfig()).embeddings.model)
        kb = failing_knowledge(embedder, (models or ModelsConfig()).knowledge, faults["knowledge"]["fail_after_searches"])
    sink = MemorySink()
    sinks: list[Any] = [sink, *(extra_sinks or [])]
    log_path = None
    if log_dir is not None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        log_path = log_dir / f"{scenario['id']}-{stamp}.jsonl"
        sinks.append(JsonlSink(log_path))
    if console:
        sinks.append(ConsoleSink())
    timeline = Timeline(sinks)
    journal = None
    if log_path is not None:  # every logged run has its twin: what came in, next to what the Brain did
        journal = JournalWriter(log_path.with_name(log_path.stem + ".inputs.jsonl"), {
            "name": scenario.get("name"), "run_id": f"{scenario['id']}-deterministic" if clock.current().deterministic else log_path.stem, "scenario": scenario["id"], "clock": "deterministic" if clock.current().deterministic else "system",
            "epoch": clock.current().now().isoformat(), "speed": speed, "policy": policy.model_dump(mode="json"),
            "models": (models or ModelsConfig()).model_dump(mode="json"), "config_hash": fingerprint(policy), "env": fingerprint_env(),
        }, os.environ.get(partners.brain.signing_secret_env, ""))

    attacks: dict[str, Any] = {}
    async with partners_context as (twin_target, guardian_client):
        if isinstance(twin_target, MqttTarget):
            twin = MqttTwinAdapter(twin_target.http, MqttConfig(reorder_ms=20), partners.twin.poll_interval_ms, stop_when_done=True, transport=twin_target.broker.transport)
        elif isinstance(twin_target, httpx.AsyncClient):
            twin = HttpTwinAdapter(twin_target, partners.twin.poll_interval_ms, stop_when_done=True)
        else:
            twin = McpTwinAdapter(twin_target, partners.twin.poll_interval_ms, stop_when_done=True)
        async with twin:
            await guardian_client.post("/admin/config", json=scenario.get("guardian", {}))
            playable = {key: scenario[key] for key in ("id", "topology", "events", "on_dispatch", "signing_keys") if key in scenario}
            await twin.call_tool("admin_load_scenario", {"scenario": playable, "speed": speed})

            guardian = RestGuardianAdapter("", guardian_client)
            if "guardian" in faults:
                from brain.faults import FlakyGuardian

                guardian = FlakyGuardian(guardian, faults["guardian"]["after_verdicts"])
            brain_twin = twin
            if "twin" in faults:
                from brain.faults import FlakyTwin

                brain_twin = FlakyTwin(twin, faults["twin"]["after_readings"], faults["twin"]["fail_attempts"])
            service = BrainService(partners, policy, JournalingTwin(brain_twin, journal) if journal else brain_twin,
                                   JournalingGuardian(guardian, journal) if journal else guardian, timeline, models,
                                   store=store, kb=kb, llm_crew=llm_crew, llm_health=llm_health, journal=journal)
            timeline.emit("brain.scenario.started", scenario["id"], {"name": scenario.get("name"), "speed": speed})
            if on_service is not None:
                on_service(service)
            await service.start()
            attacker = asyncio.create_task(_push_attacks(scenario["attacks"]["push"], service, partners, policy, models, attacks)) if scenario.get("attacks", {}).get("push") else None
            try:
                await asyncio.wait_for(service.run_until_quiet(), timeout_s)
                timed_out = False
            except TimeoutError:
                timed_out = True
            if attacker is not None:
                await attacker
            actuator_calls = (await twin.call_tool("admin_actuator_log"))["calls"]

    result = ScenarioResult(scenario["id"], log_path, sink, actuator_calls, attacks=attacks)
    result.checks = [Check("scenario finished before the timeout", not timed_out, f"{timeout_s}s")]
    crew = next((e.data["team"]["crew"] for e in sink.of("brain.started")), "scripted")
    result.checks += evaluate(scenario.get("expect", {}), sink, actuator_calls, scripted_team=crew == "scripted", attacks=attacks)
    timeline.emit("brain.scenario.finished", scenario["id"], {
        "passed": result.passed,
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in result.checks],
    })
    for candidate in sinks:
        if isinstance(candidate, JsonlSink):
            candidate.close()
    if journal is not None:
        journal.close()
    return result
