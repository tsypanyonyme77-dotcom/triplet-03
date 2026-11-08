# 0006 AI and ML methods

Status: rules, statistics, retrieval, checked agents and bounded learning built and measured; optimisation, Kalman, belief and the planner built and on by default. Decides: this team. Date: 4 Nov 2026.

## Question

Which methods does the Brain use for which question, and why not the fashionable ones? "Use a method where it earns its place; say how you know."

## The method for each question

| Question | Method | Why this one | Measured | Not chosen, and why |
| --- | --- | --- | --- | --- |
| Is this reading believable? | Forward models: each sensor predicted from its own history, a first implausible reading doubted until a second source agrees | Cheap, explainable, runs offline | `brain forward-bench` on synthetic streams with a known truth; the Academy's first run proposed `forward.z_threshold` 4.0 to 3.75 (loss 4.133 to 3.880, held-out gain 0.213; written to an overlay that is not enabled) and **rejected** `forward.alpha` (design +0.04, held-out -0.04: overfitting caught) | A learned anomaly model: no data from the Twin yet, and a score nobody can read |
| What does the playbook say? | Hybrid retrieval over 68 items, filtered before the cut | Procedures are text; filters are exact | recall@3 0.956 dense, 0.911 hybrid on 45 questions | GraphRAG: built, measured, **no gain**, off |
| What do we do about a crime? | Reflex rules, then a Police agent team (Analyst, Tactician, Chief) whose output is checked by code (`verify_case`, `verify_plan`) | Ambiguous cases need language reasoning; nothing it says reaches the Twin unchecked | Real Groq team on the earlier `b2` (the story now in `t14`): 5 of 5 passed, 4 placed a plan before the arrest, plan agreement 0.75 | An agent that acts directly; fine-tuning a model (no data, no gain a verifier would accept) |
| Which units where? | OR-Tools: min-cost flow for dispatch, CP-SAT for perimeter and load shedding | Exact, with a certificate; an LLM cannot prove optimality | **To be measured** with `brain optimise-bench` against nearest-first (plan 2) | Reinforcement learning: no simulator we trust, no safety proof |
| How soon does it overflow? | A two-state Kalman filter on level and rate | Needs only readings the Twin sends | **To be measured** against the static threshold | A neural forecaster: no data |
| How sure is the incident real? | Log-odds fusion over independent witnesses (advisory) | Calibrated and explainable | **To be measured** with a reliability table | An LLM's stated confidence |
| How does it improve? | Sleep (stories become reflexes after six checks) and the Academy (13 listed parameters, held-out, reversible) | Bounded, auditable, never uses the outcome of a dispatch | Learning curve on `b2`: team runs 1 to 0, time to last action 123.6 ms to 79.7 ms, identical decisions | Unbounded self-modification; learning from outcomes |

## Decision

Use each method for the question it answers best, put a verifier between every model and the gate, measure before adopting, and report a null result when there is one (GraphRAG, and ideas cut because they moved no number: a change-point detector, holding units back, load shedding by normalising salience). The scripted team is the default; the language model is opt-in (`--llm`) and runs on Groq's free plan with Ollama as the offline alternative. No neural network is trained: there is no data from a real Twin yet, and an opaque model cannot be checked by the gate. With real streams in Phase 2 the Academy and `brain improve` are where a learned component would be tried, on held-out stories.

## Evidence on reliability of the agents

- At `temperature` 0 the real model gave 5 different answers in 5 identical calls (4 with a seed). The Brain therefore does not claim the agents are reproducible: it records and replays them (plan 0) and bounds what they may say (verifiers, the gate).
- On Groq's free plan (8,000 tokens a minute) back-to-back deliberations are throttled; only spaced runs place a plan before a 15 s pursuit. The solver is the part that is always there.

## Cost to build

Rules, statistics, retrieval, the team and the learning are built. Plan 2 adds the engines (about 2 days for the core), plan 3 the benchmarks that give them ground truth. Risk: an engine that does not beat what it replaces; then it is a null result and stays off.

## If it fails

Every method has a fallback that is today's behaviour: nearest station, static threshold, the scripted team, no belief.

## What the triplet must agree

Only what a method needs from a partner: what a finished fire or ambulance unit reports; which sensors move together and what an actuator does to a sensor (these switch on `forward.coupled` and `forward.effects`, both built and off); what the Guardian's `confidence` means.

## Enforced or shown by

`forward-bench`, `rag-eval`, `reliability`, `optimise-bench`, `learning-curve`, `ablate`; the verifiers; a ban in code review on any model on the safety path.

## One-line answers for the jury

- *Is this AI?* It uses AI where it helps (language reasoning on ambiguous cases, retrieval), statistics and solvers where they are exact, and code for safety.
- *Why no deep learning?* No data yet, and nothing a juror could check. Phase 2 is where it would be tried.
- *Can the language model make a mistake that matters?* It can write a bad plan; the verifier rejects it, and the gate would refuse the call.
