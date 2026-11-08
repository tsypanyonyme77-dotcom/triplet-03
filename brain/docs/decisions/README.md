# Decision records

The Phase 1 text leaves eight things free: architecture, programming languages, protocols, hosting, databases, AI and ML methods, the user interface, and the scenarios. "Choose what your triplet can build and defend." One record per choice. Each states who decides (this team, the triplet, or the shared contract), the options we weighed, the decision, what we measured, what it costs to build, what we do if it fails, what the partners must agree, and the one-line answers for the jury.

| Record | Choice | Who decides | Status |
| --- | --- | --- | --- |
| [0001](0001-architecture.md) | Ports and adapters round a decision core, one gate, an event timeline | this team | built |
| [0002](0002-language.md) | Python 3.12 with types, plain JavaScript for the screen | this team | built |
| [0003](0003-protocols.md) | MCP, REST, SSE with CloudEvents, OTLP; adapters for the rest | **the triplet** | MCP and REST built; agreed with the partners |
| [0004](0004-hosting.md) | One laptop first, Compose | **the triplet** (the joint start) and this team (the Brain's images) | Compose built; agreed |
| [0005](0005-databases.md) | Memory graph, Neo4j, Qdrant, SQLite, a hash-chained log | this team | memory, Neo4j, log, SQLite and Qdrant built |
| [0006](0006-ai-ml-methods.md) | Rules, statistics, optimisation, retrieval, checked agents, bounded learning | this team | all built |
| [0007](0007-user-interface.md) | One static page served by the Brain, SSE, one vendored library | this team, for a screen the **triplet** needs (R3) | built |
| [0008](0008-scenarios.md) | A Test Book per triplet: `d1` to `d4` | **the triplet** | built; agreed |

Companions: `../HOW-IT-WORKS.md` (how the parts fit), `../SECURITY.md` (security in depth).

**How to read a record.** "Evidence" lines are commands or measurements that were run; where a number is an estimate it says so. "Cost to build" gives the state today and a rough effort in working days (my estimate, not a measurement). "What the triplet must agree" is the part that is not ours alone to decide.

**How to keep them true.** A record changes when a decision changes. A test (plan 5, task 10) fails if a free dimension has no record or a record's evidence names a command that does not exist.
