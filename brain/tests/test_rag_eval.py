"""The retrieval evaluation: the metrics are right, the question set is sound, and the held-out half cannot be used to choose anything."""

import math
from pathlib import Path

import pytest
import yaml

from brain.knowledge.embedding import HashingEmbedder
from brain.knowledge.evaluate import MODES, auc, build_knowledge_base, evaluate, load_questions, metrics, run_evaluation

QUESTIONS = Path(__file__).parent / "data" / "rag_eval.yaml"


def test_the_metrics_are_computed_on_a_known_ranking():
    ranking = ["x", "A", "y", "B", "z"]

    got = metrics(ranking, ["A", "B"])

    assert got["recall@1"] == 0 and got["recall@3"] == 0.5 and got["recall@5"] == 1.0
    assert got["mrr"] == 0.5  # the first expected item is second
    ideal = 1 / math.log2(2) + 1 / math.log2(3)
    assert got["ndcg@5"] == pytest.approx((1 / math.log2(3) + 1 / math.log2(5)) / ideal)
    assert metrics([], ["A"]) == {"recall@1": 0, "recall@3": 0, "recall@5": 0, "mrr": 0, "ndcg@5": 0}


def test_auc_is_the_chance_that_an_answerable_question_scores_above_a_nonanswer():
    assert auc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert auc([0.1], [0.9]) == 0.0
    assert auc([0.5, 0.5], [0.5]) == 0.5  # a tie is half
    assert auc([], [0.1]) is None


def test_the_question_set_is_sound():
    questions = load_questions()

    assert len(questions) >= 40 and len({q["id"] for q in questions}) == len(questions)
    for split in ("design", "heldout"):
        assert sum(q["split"] == split for q in questions) >= 20, split
    assert sum(q["kind"] == "nonanswer" for q in questions) >= 6 and sum(q["kind"] == "multihop" for q in questions) >= 8
    for department in ("POLICE", "FIRE", "MEDICAL", "MOBILITY", "DISASTER", "UTILITIES"):
        assert sum(q.get("department") == department for q in questions) >= 6, department
    assert all(q["expect"] == [] for q in questions if q["kind"] == "nonanswer")
    assert all(q["expect"] for q in questions if q["kind"] != "nonanswer")


async def test_every_expected_item_exists_in_the_corpus_the_brain_loads():
    kb = await build_knowledge_base(HashingEmbedder())

    for question in load_questions():
        for item in question["expect"]:
            assert kb.has(item), (question["id"], item)
        for action in question.get("twin_lacks", []):
            assert kb.has(f"CAP-{action}"), (question["id"], action)  # the actuator is a real one


async def test_each_mode_ranks_with_only_the_signals_it_names():
    kb = await build_knowledge_base(HashingEmbedder())
    question = next(q for q in load_questions() if q["id"] == "utl-01")

    rows = {mode: await evaluate(kb, [question], mode=mode) for mode in MODES}

    assert set(rows) == {"dense", "keyword", "hybrid", "hybrid+graph", "graphrag"}
    for mode, row in rows.items():
        assert row["questions"][0]["ranking"], mode
        assert row["questions"][0]["id"] == "utl-01"
    assert rows["dense"]["questions"][0]["ranking"] != rows["keyword"]["questions"][0]["ranking"]


async def test_the_held_out_split_is_not_used_for_choosing_anything():
    with pytest.raises(ValueError, match="held-out"):
        await run_evaluation(HashingEmbedder(), split="heldout", overrides={"knowledge.mmr": 0.3})
    with pytest.raises(ValueError, match="held-out"):
        await run_evaluation(HashingEmbedder(), split="all", overrides={"knowledge.utility_weight": 1.0})
    with pytest.raises(ValueError, match="unknown"):
        await run_evaluation(HashingEmbedder(), split="design", overrides={"knowledge.nope": 1})
    plain = await run_evaluation(HashingEmbedder(), split="heldout")
    assert plain["splits"]["heldout"]["hybrid"]["questions"] > 0


async def test_the_report_has_every_split_mode_and_kind():
    report = await run_evaluation(HashingEmbedder(), split="all")

    assert report["embedder"] == "hashing-384" and report["items"] > 60
    assert set(report["splits"]) == {"design", "heldout", "all"} and set(report["splits"]["all"]) == set(MODES)
    assert {"direct", "paraphrase", "multihop"} <= set(report["by_kind"]) and "nonanswer" not in report["by_kind"]
    assert set(report["tight_budget_multihop"]) == set(MODES) and report["tight_budget_multihop"]["hybrid"]["questions"] == 10
    assert 0 <= report["nonanswer"]["auc"] <= 1 and report["nonanswer"]["questions"] == 6
    assert yaml.safe_load(QUESTIONS.read_text())  # the file the numbers came from is still there


async def test_what_the_scripted_team_cites_is_a_subset_of_what_it_retrieved():
    from tests.test_explain import events_of

    events = await events_of("t14")
    plans = [e for e in events if e["type"] == "brain.plan.verified"]
    assert plans
    for plan in plans:
        retrieved = {hit["id"] for lookup in plan["data"]["retrieval"] for hit in lookup["hits"]}
        assert set(plan["data"]["playbook"]) <= retrieved, plan["data"]["playbook"]
