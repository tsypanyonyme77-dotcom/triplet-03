# Guardian build plan

Source of truth: `Guardian_Layer_Design.pdf` (concepts) + the build prompt (names, defaults).

## Modules

| Package | Modules | Role |
|---|---|---|
| core | `clock`, `config`, `models`, `main` | injected clock, YAML → Pydantic config, internal models, app wiring |
| adapters | `schemas/*`, `twin_client/{base,http,mcp,mqtt}`, `brain_api/*` | the only code that knows wire formats and partner transports |
| ingest | `validator`, `normalizer`, `state_store`, `pipeline` | envelope validation, Reading conversion, ring buffers + SQLite, L1→L6 orchestration |
| detectors | `authenticity` L1, `freshness` L2, `plausibility` L3a, `semantic_plausibility` L3b, `dynamics` L4, `crosscheck` L5, `liveness_rate` L6, `patterns/baseline`, `patterns/isolation_forest` (off) | one LayerResult list per layer |
| trust | `scorer`, `verdict_engine`, `signer` | weights + caps + threat tightening, signed verdicts |
| actuator_watch | `call_auditor`, `effect_verifier` (+ tiny expectation DSL) | Block B |
| threat | `attack_catalogue`, `correlator`, `threat_level`, `alerts` | Block C |
| containment | `isolate`, `quarantine`, `rollback`, `manager` | Block D |
| audit | `logger` (JSONL), `timeline_emitter` (WS fan-out) | R2 / R3 |
| mocks | `common/signing`, `twin_mock` (sim, physics, injector, tools), `brain_mock` | R1: run alone |
| scenarios | `run.py` | live trigger + log per Test Book scenario |

## Build order

1. Scaffold: pyproject, config + YAML, clock, models, schemas, signer, audit logger → unit tests
2. Ingest + L1, L2, L3a, L6 + scorer + verdict engine + `/v1/readings`, `/v1/verdicts/request` + SQLite → tests
3. Twin mock (data, signing, push) → end-to-end verdict on mock data
4. L4 (+ hour-of-day baseline), L5, L3b → tests
5. Actuator watch + twin physics + `valve_stuck` → tests
6. Containment, rollback, correlator, threat levels, alerts, WebSockets → tests
7. Brain mock, T1–T11 scenario tests, scenario CLI
8. Docker, compose, Makefile, pre-commit, README, INTERFACE.md
9. Hardening: hypothesis fuzzing, latency, restart recovery, ruff + mypy
10. Optional: Isolation Forest behind `ml.enabled`

## Key decisions

- Background loops (liveness, threat hysteresis, effect verifier, pull ingest) are thin `while: clock.sleep(); tick()`
  wrappers. Tests never start them; they advance a `FakeClock` and call `tick()` directly.
- Corroboration sources count when they are *self-consistent* (no range, semantic, rate, flatline or drift failure;
  not contained, not stale, not untrusted), not only when their last status was `trusted`. Otherwise the leading sensor of a real event (rain before flow before level)
  deadlocks every sensor at `suspect`. See README "Deviations".
- Schema / contract errors → 4xx error model. A well-formed reading with a bad HMAC → an `untrusted` verdict.

## Status (2026-10-24)

All ten steps done. 110 tests pass (unit, integration, hypothesis fuzzing, T1–T11), 97 % coverage, ruff and mypy
clean. The docker-compose stack starts healthy and the live T1, T3, T4, T6, T8, T9 and T10 runs pass. Optional
Isolation Forest is built and stays off by default (`ml.enabled: false`).
