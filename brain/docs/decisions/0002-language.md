# 0002 Programming languages

Status: accepted, built. Decides: this team. Date: 4 Nov 2026.

## Question

Which languages carry the Brain, the screen, the configuration and the scripts, given a five-week build, a laptop demo and the libraries the design needs?

## Options considered

| Option | For | Against | Verdict |
| --- | --- | --- | --- |
| Python 3.12, typed, with pydantic at the boundaries | LangGraph, LangChain clients, the MCP SDK, OR-Tools, fastembed, the Neo4j and Qdrant clients, numpy and networkx all exist here first and are maintained. Fast to change. The team knows it | Slower than compiled code; the global interpreter lock | **Chosen** |
| Go | Fast, one static binary, good concurrency | No OR-Tools of the same depth, no LangGraph, a thinner MCP and agent ecosystem | Rejected |
| Rust | Fast and safe | Same library gap, slowest to write, no benefit at millisecond decision times | Rejected |
| TypeScript on Node | One language with the screen | Weaker numeric, optimisation and graph stack; the agent tooling is younger | Rejected |
| Java or Kotlin | Mature, typed | Heavy to start and ship; Neo4j and OR-Tools are the only draws and both have Python clients | Rejected |

For the screen: plain JavaScript modules and one HTML file, no framework and no build step. Configuration is YAML and JSON. Cypher for the graph. Bash for the scripts that install and start things. Nothing else.

## Decision

Python 3.12 managed by `uv` with a lock file, type hints throughout, pydantic models for every message that crosses a boundary. The screen is vanilla JavaScript with one vendored library (three.js r160, 672 KB). The language choice has no effect on a partner: the wire is JSON over standard protocols.

## Evidence

- Decisions are fast enough: in process on this laptop, scenario `t14` shows (measured on the earlier `b2`, the same crime story) the first action 35 to 58 ms after the incident opens and the last at 117 to 470 ms (baseline file and a run on 4 Nov), against a 15 s mock pursuit.
- 11,612 lines of Python in `src/brain`, 531 in `mocks`, 7,897 in tests (580 test functions, 707 test cases), 2,618 lines of screen code.
- `uv.lock` pins every dependency; `uv sync` reproduces the environment.
- No compiled extension is built by us. OR-Tools and numpy ship wheels.

## Cost to build

Built. Risks: Python's global interpreter lock (not a bottleneck: the decision path is I/O-bound and short; solvers run with one worker and a time limit); the dependency weight added by OR-Tools (it pulls in pandas and matplotlib and moves `protobuf` from 7.36 to 6.33, which plan 2 task 1 checks before anything else).

## If it fails

If a hot path ever needs speed, it is one function behind an interface; the engines already return certificates through a small interface that a compiled implementation could satisfy.

## What the triplet must agree

Nothing. Teams use their own languages; only the wire formats are shared.

## Enforced or shown by

`ruff` and `mypy` on `contracts/` and `gate/` in CI (plan 4); the lock file; a test that the shipped config equals the defaults.

## One-line answers for the jury

- *Why Python?* The libraries we need exist here first, and our decisions take milliseconds, not minutes.
- *What does it cost you?* Raw speed we do not need, and a heavier install, which the images absorb.
- *Why no frontend framework?* One static page works offline on a projector with nothing to build.
