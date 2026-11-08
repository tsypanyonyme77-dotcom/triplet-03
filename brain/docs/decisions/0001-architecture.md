# 0001 Architecture

Status: accepted, built. Decides: this team. Date: 4 Nov 2026.

## Question

How is the Brain organised so that partners can be swapped, every action can be checked, and a jury can follow the reasoning?

## Options considered

| Option | For | Against | Verdict |
| --- | --- | --- | --- |
| Ports and adapters round a decision core, one gate, an event timeline | Partner I/O is separate from logic (a scored criterion). A new partner is one adapter class. One place decides whether an action may leave. The log explains everything | More files than a script; discipline needed to keep logic out of adapters | **Chosen** |
| One service per brain region | Looks like the diagram | Network calls between parts that share state; more to deploy and break on stage; nothing gained at this size | Rejected |
| A monolith with partner calls inside the rules | Fastest to write | Cannot be tested alone, cannot swap a partner, no single chokepoint | Rejected |
| An LLM agent that calls the Twin directly | Simple, fashionable | Nothing deterministic between a model's words and an actuator | Rejected: breaks "code disposes" |

## Decision

Three ports (`TwinPort`, `GuardianPort`, `TimelineSink` in `src/brain/ports.py`), adapters behind them, a pipeline of perception, trust, forward models, triage, an attention workspace, reflex rules and an agent team, and one gate (`src/brain/gate/`) that is the only code allowed to call an actuator. Every step writes a CloudEvent to a hash-chained timeline. The Brain is brain-inspired: it models functions of a brain (attention, prediction error, sleep, habit) and is never described as conscious. The expansion in the convergence spec adds engines inside the same shape and changes none of it. Which brain function inspired each region, how it is built and where the analogy stops: `../BRAIN-MAPPING.md`.

## Evidence

- `src/brain/ports.py` is 45 lines; `adapters/` holds two implementations (MCP for the Twin, REST for the Guardian); `mocks/` holds stand-ins of both partners (531 lines), so the Brain runs alone (R1).
- `call_actuator` has exactly one call site, in the gate (`grep -rn call_actuator src`), and an invariant test will pin it (plan 6 task 2).
- The seven temporal promises TS-01 to TS-07 (for example trust before action, nothing after an incident closes) hold on all five scenarios (`brain verify-log --scenarios`).
- 60 of 60 held-out variants decide as their base scenario (`brain variants --seeds 1000-1004`).
- `brain ablate` switches each region off in turn to show what it is worth.
- Size: 11,612 lines in `src/brain`, 7,897 lines of tests.

## Cost to build

Built. The additions in plans 0 to 6 are each a module behind a config switch. Risk: the module count grows; the code map (`docs/codebase/CODEBASE.md`) and a rule that new code reads like its neighbours keep it navigable.

## If it fails

The ports are the exit: a partner with a different protocol needs one adapter class. If a region misbehaves, its config switch turns it off and the scenarios still decide as recorded.

## What the triplet must agree

Nothing about the inside. Only the surfaces: the Interface Card (`INTERFACE.md`), the contract (`contracts/`) and how the three layers connect (`INTEGRATION.md`, written with the partners).

## Enforced or shown by

The conformance kit (plan 1), the "only the gate calls the Twin" invariant test (plan 6), the architecture diagrams, the code map.

## One-line answers for the jury

- *Why not microservices?* Parts that share state do not need a network between them. We do separate what a partner can change: its two ports.
- *Where is the safety decision?* In one file, by code, never in a model.
- *Can you run it without partners?* Yes: `uv run brain scenario t14 --inproc --speed 0`.
