"""The knowledge the departments reason from: every department has a playbook that only asks for what the Twin can do."""

from brain.config import ModelsConfig
from brain.departments import load_manifest
from brain.knowledge import KnowledgeItem, load_playbook, playbook_exists
from brain.knowledge.corpus import load_reference
from brain.knowledge.embedding import HashingEmbedder
from brain.knowledge.memory import MemoryKnowledgeBase
from brain.scenario import inproc_partners, load_scenario, run_scenario
from tests.test_explain import events_of

HASHING = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})
DEPARTMENTS = {"POLICE": "crime", "FIRE": "fire", "MEDICAL": "accident", "MOBILITY": "jam", "DISASTER": "flood", "UTILITIES": "overload smog"}


def all_playbooks() -> list[KnowledgeItem]:
    return [item for code in DEPARTMENTS for item in load_playbook(code)]


def test_every_department_has_a_playbook_of_at_least_six_items():
    for code in DEPARTMENTS:
        assert playbook_exists(code), code
        assert len(load_playbook(code)) >= 6, code


def test_every_incident_type_has_at_least_two_items_that_apply_to_it():
    items = all_playbooks()
    for code, types in DEPARTMENTS.items():
        assert set(types.split()) == set(load_manifest(code.lower()).incident_types), code
        for incident_type in types.split():
            applying = [i for i in items if i.department == code and incident_type in i.applies_to]
            assert len(applying) >= 2, (code, incident_type)


def test_every_applies_to_names_a_known_incident_type():
    known = {t for types in DEPARTMENTS.values() for t in types.split()}
    for item in all_playbooks():
        assert set(item.applies_to) <= known, (item.id, item.applies_to)


async def test_every_playbook_item_uses_only_actions_the_twin_reports():
    started = next(e for e in await events_of("d1") if e["type"] == "brain.started")
    twin = set(started["data"]["capabilities"])
    for item in all_playbooks():
        assert set(item.uses) <= twin, (item.id, set(item.uses) - twin)


def test_ids_are_unique_and_carry_their_departments_prefix():
    items = all_playbooks()
    assert len({i.id for i in items}) == len(items)
    # Fire and ambulance, and floods and utilities, were one pack each: the ids they had kept their prefix, and the new ones carry the new pack's.
    prefix = {"POLICE": ("POL-PB-",), "FIRE": ("FEM-PB-",), "MEDICAL": ("FEM-PB-", "MED-PB-"), "MOBILITY": ("MOB-PB-",), "DISASTER": ("UTL-PB-", "DIS-PB-"), "UTILITIES": ("UTL-PB-",)}
    assert all(i.id.startswith(prefix[i.department]) and i.kind == "playbook" for i in items)


def test_a_reference_document_is_cut_into_section_aware_chunks_under_the_word_limit(tmp_path):
    document = tmp_path / "GUIDE.md"
    document.write_text("# Guide\n\nIntro words here.\n\n## Alpha\n\n" + "one two three four five six seven eight nine ten. " * 12 +
                        "\n\nSecond paragraph of alpha.\n\n```json\n{\"skip\": true}\n```\n\n## Beta\n\nBeta text.\n")

    chunks = load_reference(document, max_words=40)

    assert [c.kind for c in chunks] == ["reference"] * len(chunks)
    assert chunks[0].id == "REF-GUIDE-01" and chunks[0].title == "Guide"
    longest = max(chunks, key=lambda c: len(c.text.split()))  # a single long paragraph is kept whole, never cut mid-sentence
    assert longest.title == "Guide > Alpha" and longest.text.startswith("one two") and "Second paragraph" not in longest.text
    assert all(len(c.text.split()) <= 40 for c in chunks if c is not longest)
    assert {c.title for c in chunks} == {"Guide", "Guide > Alpha", "Guide > Beta"}
    assert not any("skip" in c.text for c in chunks)  # code blocks are not knowledge
    beta = next(c for c in chunks if c.title.endswith("Beta"))
    assert beta.text == "Beta text."


async def test_the_runtime_loads_every_departments_playbook_rules_and_the_interface_card():
    kb = MemoryKnowledgeBase(HashingEmbedder())

    result = await run_scenario(load_scenario("d3"), inproc_partners(), models=HASHING, speed=0, timeout_s=30, kb=kb)

    assert result.passed
    for item_id in ("POL-PB-001", "FEM-PB-001", "MOB-PB-001", "UTL-PB-001", "FIR-001", "MOB-001", "UTL-002", "CAP-dispatch_unit"):
        assert kb.has(item_id), item_id
    assert any(i.startswith("REF-INTEGRATION-BRAIN-") for i in kb.items)


async def test_a_police_search_never_returns_another_departments_procedure():
    kb = MemoryKnowledgeBase(HashingEmbedder())
    await run_scenario(load_scenario("d1"), inproc_partners(), models=HASHING, speed=0, timeout_s=30, kb=kb)

    hits = await kb.search("a fire is burning, send the fire engine", department="POLICE", kinds={"playbook"}, k=5)

    assert hits and all(h.id.startswith("POL-PB-") for h in hits)
    fire = await kb.search("a fire is burning, send the fire engine", department="FIRE", kinds={"playbook"}, k=3)
    assert fire[0].id.startswith("FEM-PB-")
