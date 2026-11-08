"""The conformance kit: one command tells a stranger whether a Twin, a Guardian or a Brain follows the contract. It must pass on the shipped
mocks and fail, by name, on each mock with one defect."""

import os

import httpx

from brain.api import Hub, create_app
from brain.baseline import MODELS
from brain.config import PartnersConfig, Policy
from brain.conformance import run_brain, run_guardian, run_twin, summary
from mocks.guardian.engine import MockGuardian
from mocks.guardian.server import build_app
from mocks.twin.engine import MockTwin
from mocks.twin.server import build_server

TWIN_SECRET, BRAIN_SECRET = "kit-twin-secret", "kit-brain-secret"


def by_id(results):
    return {r.id: r for r in results}


def failing(results):
    return {r.id for r in results if r.status == "fail"}


# ---- one defect each


class UnsignedTwin(MockTwin):
    def __init__(self):
        super().__init__(None, BRAIN_SECRET)  # sends no signature


class RepeatingSequenceTwin(MockTwin):
    def list_readings(self, cursor=0, limit=200):
        page = super().list_readings(cursor, limit)
        for reading in page["readings"]:
            reading["sequence_no"] = 1
        return page


class TwinThatSendsAnotherUnit(MockTwin):
    def _dispatch(self, call):
        self._dispatched.clear()  # forgets what it already sent, so a repeat sends a second unit
        return super()._dispatch(call)


def twin_server(twin=None, without=()):
    server = build_server(twin or MockTwin(TWIN_SECRET, BRAIN_SECRET))
    for name in without:
        server.remove_tool(name)
    return server


async def test_the_kit_passes_against_the_shipped_mock_twin():
    results = await run_twin(twin_server(), TWIN_SECRET, brain_secret=BRAIN_SECRET, probe=True)

    assert failing(results) == set(), [(r.id, r.detail) for r in results if r.status == "fail"]
    assert {"T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"} <= {r.id for r in results if r.status == "pass"}


async def test_a_twin_without_get_topology_fails_t1():
    assert "T1" in failing(await run_twin(twin_server(without=["get_topology"]), TWIN_SECRET))


async def test_unsigned_readings_fail_t4():
    assert "T4" in failing(await run_twin(twin_server(UnsignedTwin()), TWIN_SECRET))


async def test_a_repeating_sequence_fails_t5():
    assert "T5" in failing(await run_twin(twin_server(RepeatingSequenceTwin(TWIN_SECRET, BRAIN_SECRET)), TWIN_SECRET))


async def test_a_second_dispatch_that_sends_another_unit_fails_t8():
    results = await run_twin(twin_server(TwinThatSendsAnotherUnit(TWIN_SECRET, BRAIN_SECRET)), TWIN_SECRET, brain_secret=BRAIN_SECRET, probe=True)

    assert "T8" in failing(results)


async def test_actuators_are_not_called_without_the_probe_flag():
    twin = MockTwin(TWIN_SECRET, BRAIN_SECRET)

    await run_twin(build_server(twin), TWIN_SECRET, brain_secret=BRAIN_SECRET)

    assert twin.actuator_log == []


def guardian_client(guardian):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=build_app(guardian)), base_url="http://guardian")


async def test_the_kit_passes_against_the_shipped_mock_guardian():
    async with guardian_client(MockGuardian(TWIN_SECRET)) as client:
        results = await run_guardian(client, TWIN_SECRET)

    assert failing(results) == set(), [(r.id, r.detail) for r in results if r.status == "fail"]
    assert {"G1", "G3", "G4", "G5"} <= {r.id for r in results if r.status == "pass"}
    assert by_id(results)["G2"].status == "warn"  # the mock does not check sequence_no: a warning, the Brain checks replay itself


async def test_a_guardian_that_trusts_a_tampered_reading_fails_g2():
    async with guardian_client(MockGuardian(None)) as client:  # checks no signature at all
        assert "G2" in failing(await run_guardian(client, TWIN_SECRET))


async def test_the_kit_passes_against_our_own_brain(tmp_path):
    os.environ.setdefault("BRAIN_APPROVAL_SECRET", "x")
    hub = Hub(PartnersConfig(), Policy(), MODELS, mocks="inproc", log_dir=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        results = await run_brain(client)

    assert failing(results) == set(), [(r.id, r.detail) for r in results if r.status == "fail"]
    assert {"B1", "B2", "B3", "B4", "B5"} <= {r.id for r in results if r.status == "pass"}


def test_the_report_names_the_failing_check_and_what_to_change():
    from brain.conformance import Result, markdown

    text = markdown("2026-11-04", [Result("T5", "twin", "sequence_no increases per sensor", "fail", "cam-1: 1 then 1", "make sequence_no increase for each sensor")])

    assert "T5" in text and "FAIL" in text and "make sequence_no increase" in text
    assert summary([Result("T5", "twin", "x", "fail", "", "")]) == (0, 0, 1, 0)
