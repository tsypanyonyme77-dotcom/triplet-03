"""A signed explanation: it verifies, any change breaks it, and another key is refused."""

import copy

from brain.explain import explain_decision
from brain.explain.bundle import make_bundle, verify_bundle
from brain.timeline import read_log
from tests.test_explain import run

KEY = "audit-key"


async def bundle_of(tmp_path):
    result = await run("t14", log_dir=tmp_path)
    events = read_log(result.log_path)
    return make_bundle(explain_decision(events, "dec-0003"), events, KEY)


async def test_a_bundle_verifies_and_holds_only_the_lines_it_rests_on(tmp_path):
    bundle = await bundle_of(tmp_path)

    ok, message = verify_bundle(bundle, KEY)

    assert ok, message
    assert {row["id"] for row in bundle["log_slice"]} == {s["event_id"] for s in bundle["explanation"]["steps"]}
    assert bundle["provenance"]["signed_by"] == "city_brain" and bundle["chain_head"]


async def test_changing_one_log_line_or_one_fact_breaks_the_bundle(tmp_path):
    bundle = await bundle_of(tmp_path)

    fact = copy.deepcopy(bundle)
    fact["explanation"]["steps"][0]["fact"] = "A different thing happened."
    line = copy.deepcopy(bundle)
    line["log_slice"][0]["data"]["summary"] = "level 9.99 m"

    assert "signature" in verify_bundle(fact, KEY)[1] and not verify_bundle(fact, KEY)[0]
    assert not verify_bundle(line, KEY)[0]


async def test_an_attacker_who_resigns_still_cannot_forge_a_log_line(tmp_path):
    from brain.contracts.signing import sign

    bundle = await bundle_of(tmp_path)
    forged = copy.deepcopy(bundle)
    forged["log_slice"][0]["data"]["summary"] = "level 9.99 m"
    forged = sign({k: v for k, v in forged.items() if k != "provenance"}, KEY, "city_brain")  # signed again, even with the key

    ok, message = verify_bundle(forged, KEY)

    assert not ok and "its own hash" in message  # the line's chain hash no longer matches what was written


async def test_a_bundle_made_with_another_key_is_refused(tmp_path):
    bundle = await bundle_of(tmp_path)

    assert verify_bundle(bundle, "someone-elses-key")[0] is False
