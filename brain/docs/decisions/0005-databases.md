# 0005 Databases and stores

Status: memory graph, Neo4j (on by default), Qdrant (on by default), JSONL log and SQLite state, all built. Decides: this team. Date: 4 Nov 2026.

## Question

Where does the Brain keep what it knows (the city, the playbooks, past stories), what it decided (the record) and what it must survive a restart with, so that no outage slows a decision?

## Options considered

| Option | For | Against | Verdict |
| --- | --- | --- | --- |
| One store for everything (Postgres with pgvector, or Neo4j alone) | One thing to run | A graph store is a clumsy vector index and the reverse; provenance queries become joins nobody can read | Rejected as the only store |
| In-memory graph on the decision path (networkx) | No network hop; decisions never wait; trivially testable | Lost on exit | **Chosen for decisions** |
| Neo4j 5.26 Community, written behind the memory graph | Traversals and provenance read as paths; Cypher on screen; every cited id resolves | Java 21; 676 MB on disk; optional | **Chosen for provenance and analytics** |
| Qdrant (local mode and server) | Dense plus sparse search with payload filters fused on the server; persists vectors; the same client offline and in a cluster | One more service; adopted only if `rag-eval` does not show it worse | **Adopted for knowledge and stories** |
| SQLite | Stdlib, one file, durable | Not for search | **Chosen for state, checkpoints, approvals** |
| A hash-chained JSONL log | Append-only, human readable, verifiable | No queries | **Chosen as the record** |

## Decision

Five stores, one question each: the in-memory graph (what connects, on the decision path), Neo4j (why, and what fails, through Cypher), Qdrant (what we know and what is similar), the event log (what happened, in order, tamper-evident), SQLite (what state we are in). Neo4j and Qdrant are both on by default and neither is on the decision path: Neo4j is written behind the memory graph, Qdrant is read for context. Qdrant runs embedded (a folder, no server) for `uv run`, and as a server in Compose. If either stops, the Brain reports it once and carries on from memory.

## Evidence

- Parity: the memory and Neo4j knowledge bases return the same ids for the same query (`tests/test_knowledge.py`); every id a decision cites resolves in Neo4j (`tests/test_neo4j.py`, run against Neo4j 5.26.32 on 2 Nov).
- Retrieval, 45 answerable questions written before any run (`brain rag-eval`, `docs/baseline/2026-11-02-rag-eval.json`): with the real embedder dense search has recall@3 0.956 and plain hybrid 0.911, both MRR about 0.89; with the hashing embedder keyword search is best at 0.822. **GraphRAG is a null result**: identical to hybrid on every metric, so it ships off.
- Start-up cost: the 68-item corpus is embedded at every start, part of the 11.7 s measured with the real embedder. Qdrant persists vectors; expected to remove it, **not yet measured**.
- The log's hash chain is verified by `brain verify-log`; it is not yet anchored (plan 6 task 7).

## Cost to build

Memory, Neo4j, log and SQLite: built. Qdrant backend and its evaluation rows: about 1.5 days. Risk: Qdrant is no better than memory on 68 items; the record then says "the same, but it persists, filters natively and serves a cluster", and the default stays.

## If it fails

Each store has a named fallback (memory graph, in-memory index, scripted team). A scenario can stop the vector store mid-run (the `knowledge` fault in `faults.py`; no demo scenario uses it now, `tests/test_resilient_kb.py` covers it) and check that decisions do not change and that the outage is reported once (`brain.degraded`). Writing it showed the resilient wrapper was never connected to the timeline in a real run; the runtime now connects it. A Qdrant server can also do the hybrid search itself (`graph.qdrant_fusion: server`): top-3 agrees with the Brain's own fusion on 43 of 45 evaluation questions (mean overlap 0.993), measured embedded on 5 Nov.

## What the triplet must agree

Nothing: stores are internal. The only shared surface is what the Brain exposes about its provenance (`GET /api/decisions/{id}`, the PROV export), which partners may read.

## Enforced or shown by

`brain rag-eval --backend all`, the parity tests, the degraded-mode events, `brain verify-log`.

## One-line answers for the jury

- *Why five stores?* Each answers a question the others answer badly, and the decision path reads memory only.
- *Why Neo4j and Qdrant both?* They hold different things. Neo4j holds the City Graph, where the value is the links: reading → verdict → incident → decision → action, so "why was this unit sent?" is one Cypher path a juror can see. Qdrant holds the knowledge vectors, where the value is similarity: an agent asks "what do we do about this?" and gets the closest playbook items, filtered by department and available actions. A graph database is a clumsy vector index and a vector database cannot follow a chain of causes, so one store would do one job badly.
- *What does Qdrant buy over memory, honestly?* On 68 playbook items, retrieval quality is the same (`docs/baseline/2026-11-02-rag-eval.json`). What it adds is persistence (a warm start re-embeds nothing), native filters, a server-side hybrid search that agrees with ours on 43 of 45 questions, and the same client from a laptop to a cluster.
- *What if Neo4j dies?* One degraded event; decisions unchanged.
- *Did GraphRAG help?* No. We measured it, report it and left it off.
