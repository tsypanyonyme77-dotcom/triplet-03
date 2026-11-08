"""LLMHealth: a model that stops answering sends the team to its scripted stand-ins at once, and the screen is told why."""

import pytest

from brain.departments.team import LLMCrew
from brain.llm_health import LLMDown, LLMHealth, ProbeError, classify


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def health(clock=None):
    events: list[tuple[str, dict]] = []
    return LLMHealth(lambda kind, subject, data: events.append((kind, data)), now=clock or Clock()), events


def groq_error(status, message):
    error = RuntimeError(message)
    error.status_code = status
    return error


@pytest.mark.parametrize(("error", "kind"), [
    (groq_error(401, "Invalid API Key"), "key_rejected"),
    (groq_error(429, "Rate limit reached for model on tokens per day (TPD): Limit 100000"), "quota_exhausted"),
    (groq_error(429, "Rate limit reached for model on tokens per minute (TPM): Limit 8000"), "rate_limited"),
    (groq_error(503, "overloaded"), "unreachable"),
    (ProbeError(401, "bad key"), "key_rejected"),
    (ValueError("the answer did not match the schema"), None),
])
def test_an_error_from_the_model_client_is_named_by_its_cause(error, kind):
    assert classify(error) == kind


def test_the_cause_is_found_behind_a_wrapping_error():
    try:
        try:
            raise groq_error(401, "nope")
        except RuntimeError as inner:
            raise ValueError("agent failed") from inner
    except ValueError as outer:
        assert classify(outer) == "key_rejected"


def test_a_rejected_key_trips_at_once_and_the_model_is_skipped_until_the_cool_down_ends():
    clock = Clock()
    h, events = health(clock)
    h.failed(groq_error(401, "Invalid API Key"))
    assert h.state == "down" and events == [("brain.llm.status", {"state": "down", "reason": "key_rejected", "why": "the API key was rejected"})]
    with pytest.raises(LLMDown):
        h.gate()
    clock.t = 301
    h.gate()  # one call is let through to see whether it is back
    h.ok()
    assert h.state == "live" and events[-1][1]["state"] == "live"


def test_one_lost_connection_is_not_an_outage_but_two_in_a_row_are():
    h, _ = health()
    h.failed(groq_error(503, "x"))
    h.gate()
    h.failed(groq_error(503, "x"))
    with pytest.raises(LLMDown):
        h.gate()


def test_a_bad_answer_does_not_count_against_the_model():
    h, events = health()
    h.failed(ValueError("schema"))
    assert h.state == "live" and events == []


def test_a_person_can_force_the_scripted_team_and_hand_it_back():
    h, events = health()
    h.force(True)
    with pytest.raises(LLMDown):
        h.gate()
    h.force(False)
    h.gate()
    assert [e[1]["state"] for e in events] == ["scripted", "live"]


def test_the_same_state_is_announced_once():
    h, events = health()
    h.failed(groq_error(429, "per day"))
    h.failed(groq_error(429, "per day"))
    assert len(events) == 1


async def test_a_crew_with_a_down_model_raises_before_any_model_is_built_or_called():
    crew = LLMCrew({"analyst": "groq:x"}, {"analyst": []}, model_factory=lambda spec, **o: object())
    crew.health, _ = health()
    crew.health.failed(groq_error(401, "Invalid API Key"))
    with pytest.raises(LLMDown):
        await crew._run("analyst", {}, None)


async def test_a_crew_reports_a_failed_call_to_the_health_and_still_raises():
    crew = LLMCrew({"analyst": "groq:x"}, {"analyst": []}, model_factory=lambda spec, **o: object())
    crew.health, _ = health()

    async def boom(*a, **k):
        raise groq_error(401, "Invalid API Key")

    crew._run_agent = boom
    with pytest.raises(RuntimeError):
        await crew._run("analyst", {}, None)
    assert crew.health.state == "down"
