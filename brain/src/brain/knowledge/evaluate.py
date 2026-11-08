"""Measuring retrieval: a fixed set of questions with known answers, scored by four ways of searching.

`tests/data/rag_eval.yaml` holds the questions. They were written before anything was run on them and are split in two: the *design*
half may be looked at and used to choose retrieval switches, the *held-out* half is only ever reported. Asking for a switch
(`overrides`) on the held-out half is refused, so that nothing can be tuned on it by accident.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from brain.config import KnowledgeConfig, ModelsConfig
from brain.knowledge.embedding import Embedder
from brain.knowledge.memory import MemoryKnowledgeBase

MODES = ("dense", "keyword", "hybrid", "hybrid+graph", "graphrag")
K_SEARCH = 10
QUESTIONS = Path(__file__).resolve().parents[3] / "tests" / "data" / "rag_eval.yaml"
METRICS = ("recall@1", "recall@3", "recall@5", "mrr", "ndcg@5")
SETTINGS = {"knowledge.mmr", "knowledge.utility_weight"}


def load_questions(path: Path = QUESTIONS) -> list[dict[str, Any]]:
    return yaml.safe_load(path.read_text())["questions"]


def metrics(ranking: list[str], expect: list[str]) -> dict[str, float]:
    """Recall at 1, 3 and 5 (the share of the expected items found), the reciprocal rank of the first one, and nDCG at 5."""
    wanted = set(expect)
    out = {f"recall@{k}": len(wanted & set(ranking[:k])) / len(wanted) for k in (1, 3, 5)}
    first = next((rank for rank, item in enumerate(ranking, 1) if item in wanted), None)
    out["mrr"] = 1 / first if first else 0
    gain = sum(1 / math.log2(rank + 1) for rank, item in enumerate(ranking[:5], 1) if item in wanted)
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(wanted), 5) + 1))
    out["ndcg@5"] = gain / ideal if ideal else 0
    return out


def auc(answerable: list[float], unanswerable: list[float]) -> float | None:
    """The chance that a question with an answer scores above one without (a tie counts half). 0.5 is no better than chance."""
    if not answerable or not unanswerable:
        return None
    wins = sum(1.0 if a > u else 0.5 if a == u else 0.0 for a in answerable for u in unanswerable)
    return wins / (len(answerable) * len(unanswerable))


async def build_knowledge_base(embedder: Embedder, options: KnowledgeConfig | None = None, backend: str = "memory") -> MemoryKnowledgeBase:
    """The knowledge base the Brain itself loads at start-up (every department's playbook and rules, the Twin's actuators, the
    interface card), obtained by starting a calm scenario against the mock partners."""
    from brain.scenario import inproc_partners, load_scenario, run_scenario

    if backend in ("qdrant", "qdrant-hybrid"):
        from brain.knowledge.qdrant import QdrantKnowledgeBase

        kb = QdrantKnowledgeBase(embedder, options, fusion="server" if backend == "qdrant-hybrid" else "client")
    else:
        kb = MemoryKnowledgeBase(embedder, options)
    hashing = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})  # only the knowledge base's own embedder matters here
    await run_scenario(load_scenario("t12"), inproc_partners(), models=hashing, speed=0, timeout_s=30, kb=kb)
    return kb


async def evaluate(kb: MemoryKnowledgeBase, questions: list[dict[str, Any]], *, mode: str, k: int = K_SEARCH) -> dict[str, Any]:
    """One mode over some questions. `dense` and `keyword` rank with that signal alone; `hybrid` fuses both; `hybrid+graph` also
    lets the incident type pull in the items linked to it; `graphrag` adds the walk along the playbooks' links."""
    assert mode in MODES, mode
    twin = {item[4:] for item in kb.items if item.startswith("CAP-")}
    rows = []
    options = kb.options
    kb.options = options.model_copy(update={"graphrag": "local" if mode == "graphrag" else "off"})
    for q in questions:
        department = q.get("department")
        actions = twin - set(q.get("twin_lacks", [])) if department else None
        hits, trace = await kb.search_traced(
            q["question"], incident_type=q.get("incident_type") if mode in ("hybrid+graph", "graphrag") else None,
            department=department, available_actions=actions, kinds=set(q["kinds"]) if q.get("kinds") else None, k=k,
        )
        ranking = ([i for i, _, _ in trace.signals["vector"]] if mode == "dense"
                   else [i for i, _, _ in trace.signals["keyword"]] if mode == "keyword" else [h.id for h in hits])
        row = {"id": q["id"], "kind": q["kind"], "split": q["split"], "ranking": ranking}
        if q["expect"]:
            row.update(metrics(ranking, q["expect"]))
        rows.append(row)
    kb.options = options
    return {"mode": mode, "questions": rows}


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in rows if "mrr" in r]
    return {"questions": len(answerable), **{m: round(sum(r[m] for r in answerable) / len(answerable), 4) for m in METRICS}} if answerable else {"questions": 0}


async def run_evaluation(embedder: Embedder, *, split: str = "all", overrides: dict[str, float] | None = None, backend: str = "memory") -> dict[str, Any]:
    """Every mode over the chosen split. `overrides` (`knowledge.mmr`, `knowledge.utility_weight`) are for choosing switches on the
    design half; with the held-out half in the run they are refused."""
    overrides = overrides or {}
    if unknown := set(overrides) - SETTINGS:
        raise ValueError(f"unknown setting {sorted(unknown)}; the ones that can be tried are {sorted(SETTINGS)}")
    if overrides and split != "design":
        raise ValueError("a setting may only be tried on the design questions: the held-out ones are never used to choose anything")
    questions = [q for q in load_questions() if split == "all" or q["split"] == split]
    options = KnowledgeConfig(**{key.split(".", 1)[1]: value for key, value in overrides.items()})
    kb = await build_knowledge_base(embedder, options, backend)

    results = {mode: (await evaluate(kb, questions, mode=mode))["questions"] for mode in MODES}
    groups = {"design": "design", "heldout": "heldout"} if split == "all" else {split: split}
    splits = {name: {mode: aggregate([r for r in rows if r["split"] == name]) for mode, rows in results.items()} for name in groups}
    if split == "all":
        splits["all"] = {mode: aggregate(rows) for mode, rows in results.items()}
    kinds = sorted({q["kind"] for q in questions} - {"nonanswer"})
    by_kind = {kind: {mode: aggregate([r for r in rows if r["kind"] == kind]) for mode, rows in results.items()} for kind in kinds}

    # A tight budget: what an agent with room for two items gets. At ten, a department's whole playbook comes back and nothing can
    # tell the modes apart. (Added after the first run showed that; chosen before it was measured.)
    wanted = {q["id"]: q["expect"] for q in questions if q["kind"] == "multihop"}
    tight = {}
    for mode in MODES:
        rows = (await evaluate(kb, [q for q in questions if q["id"] in wanted], mode=mode, k=2))["questions"]
        tight[mode] = {"questions": len(rows), "recall@2": round(sum(len(set(r["ranking"][:2]) & set(wanted[r["id"]])) / len(wanted[r["id"]]) for r in rows) / len(rows), 4) if rows else None}
    best, none = [], []
    for q in questions:  # the strongest vector match anywhere in the corpus, whatever the filters
        top = (await kb.search_traced(q["question"], k=1))[1].signals["vector"]
        (best if q["expect"] else none).append(top[0][2] if top else 0.0)
    return {
        "date": datetime.now(UTC).strftime("%Y-%m-%d"), "embedder": embedder.name, "items": len(kb.items), "split": split,
        "overrides": overrides, "k_search": K_SEARCH, "splits": splits, "by_kind": by_kind, "tight_budget_multihop": tight,
        "nonanswer": {"questions": len(none), "auc": auc(best, none), "mean_top_vector_score_answerable": round(sum(best) / len(best), 4) if best else None,
                      "mean_top_vector_score_nonanswer": round(sum(none) / len(none), 4) if none else None},
        "misses": {mode: [r["id"] for r in rows if "recall@5" in r and r["recall@5"] < 1] for mode, rows in results.items()},
    }
