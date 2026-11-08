"""A Guardian that answers for a while and then goes quiet, so a scenario can show the Brain carrying on without trust verdicts."""

import pytest

from brain.faults import FlakyGuardian
from brain.ports import GuardianUnavailable


class Answering:
    def __init__(self):
        self.asked = 0

    async def get_verdict(self, reading, deadline_s):
        self.asked += 1
        return f"verdict-{self.asked}"

    async def is_quarantined(self, device_id):
        return False


async def test_a_guardian_that_goes_quiet_answers_then_raises():
    inner = Answering()
    guardian = FlakyGuardian(inner, after_verdicts=3)

    assert [await guardian.get_verdict({}, 1.0) for _ in range(3)] == ["verdict-1", "verdict-2", "verdict-3"]
    with pytest.raises(GuardianUnavailable, match="guardian is down"):
        await guardian.get_verdict({}, 1.0)
    assert inner.asked == 3  # the real Guardian is not asked once it is "down"


async def test_a_quiet_guardian_cannot_say_whether_a_device_is_quarantined():
    guardian = FlakyGuardian(Answering(), after_verdicts=1)

    assert await guardian.is_quarantined("cam-1") is False  # still up: nothing has been asked yet
    await guardian.get_verdict({}, 1.0)
    with pytest.raises(GuardianUnavailable):
        await guardian.is_quarantined("cam-1")
