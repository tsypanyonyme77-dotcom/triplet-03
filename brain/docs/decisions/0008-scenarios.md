# 0008 Scenarios (the Test Book)

Status: five scenarios, all pass. Written up as `d1` to `d4` on 7 Nov; since renumbered `t12` to `t15` in the shared Test Book, with `t16` (a quarantined police station) added on 8 Nov (see the table below, and `TESTBOOK-brain.md`). Replaces the 42-scenario Test Book (`b1` to `b42`) of 4 to 6 Nov, deleted on 7 Nov 2026 and recoverable from git history. **Decides: the triplet** (one Test Book per triplet; each layer is judged by how its own layer behaves).

## Question

Which scenarios prove the system works, so that "taken together, the Test Book tests all three layers and every interaction between them"?

## What the Phase 1 text requires

Scenarios are ours; there is no mandatory list and no minimum. Each uses the same fields: ID, name, layers involved, description, trigger (one command or button), expected Twin, expected Guardian, expected Brain, how to verify. Every scenario starts with one trigger and leaves a log in the repository (R2). The Test Book is one page of the report. Scenarios not run live are checked through the logs.

## Options considered

| Option | For | Against | Verdict |
| --- | --- | --- | --- |
| Scenarios written from the code's claims, with expectations at two levels (whoever deliberates; what the scripted team does) | They test what we say we do; the same files run in process, over the network mocks and in CI | Written by us, so they can share our blind spots | **Chosen**, with held-out variants as a check |
| Scenarios copied from the brief | Familiar | The brief imposes none; they would not exercise our reasoning | Rejected |
| Randomly generated scenarios | Wide | Expected outputs are not known | Used only as variants of a base scenario (shift in time, new seed, decoys) that must decide as the base |

## Decision

A Test Book of four scenarios, each proving one claim in about two minutes and explainable in one sentence. The 42 earlier scenarios could not be explained to a jury in a live slot, so they were deleted rather than hidden.

| ID | Name | Claim it proves |
| --- | --- | --- |
| `d1` | A calm day | The Brain does not overreact |
| `d2` | A fake flood | A lying sensor cannot make the Brain act: the gate refuses the warning and the valve call, with the reason |
| `d3` | A crime and a pursuit | A real incident is handled by the police team, and only through the gate |
| `d4` | A flood, an attack and a layer down | The city keeps working when something goes wrong: the harbour is warned, the valve is held, no police are sent, and the Guardian going silent is said once |
| `t16` (new) | A quarantined police station | The Guardian's quarantine reaches the gate: calls to the quarantined station are refused with reason `quarantine` and another station is used |

Each has a trigger (`scenarios/triggers/dN.sh`), declared expectations in its JSON, a canonical log in `logs/canonical/`, a recorded decision list in `docs/baseline/2026-11-07-demo-frozen.json`, and held-out variants from seeds never used for tuning (50 of 50 decide as their base).

## Coverage against the Phase 1 interaction list

| Interaction | Covered by |
| --- | --- |
| Twin to Brain | `d1`, `d3` |
| Twin to Guardian | `d2` (a reading the Guardian does not trust) |
| Brain to Guardian | `d2`, `d3`, `t16` (every call carries a trusted verdict, or is held) |
| All three, with a layer down | `d4` |

A test (`tests/test_phase1_requirements.py`) fails if a scenario lacks its fields, its trigger or its canonical log.

## What was lost

The tests that pinned the deleted stories went with them. Early flood alerts, coupled sensors, key rotation, forged pushes, hostile ids, the Twin going away and the fire, medical, traffic and utilities desks no longer have an end-to-end scenario; unit tests, `brain redteam` (24 attacks) and `tests/test_security.py` carry what they can. This is stated in the report.

## Evidence

- All five pass in process and over the network mocks; their logs have intact hash chains.
- The frozen baseline `2026-11-07-demo-frozen.json` must not change; `brain baseline --check` enforces it.
- **None has run against the real Twin or Guardian.**

## If it fails

A scenario that needs a partner feature the partner lacks is run against our mock and labelled so; the report says which ran against real partners and which against stand-ins.

## Agreed with the triplet

How a scenario is triggered on the real Twin (our mock has an admin tool that the contract does not name); who owns `scenarios/` at the triplet root; the shared Test Book page. Agreed with the Twin and Guardian teams as set out in this record.

## Enforced or shown by

`brain baseline --check`, `brain variants`, `brain verify-log`, the generated `docs/TESTBOOK-brain.md`, `tests/test_phase1_requirements.py`, `brain rehearse`.

## One-line answers for the jury

- *Do your scenarios cover every interaction?* Yes: four, one per row of the interaction list, and a test fails if one loses its fields.
- *How do I know the tests are not rigged?* Variants from seeds never used in design must decide as their base; 50 of 50 do.
- *What ran against the real partners?* Say it plainly: today, nothing.
