"""The bus: ordered, in-process delivery of typed messages."""

import logging

from brain.mind.bus import Bus, IncidentClosed, IncidentTouched


async def test_a_published_message_reaches_every_subscriber_of_its_type_in_order():
    bus, heard = Bus(), []
    bus.subscribe(IncidentTouched, lambda m: heard.append(("first", m.incident_ids)))
    bus.subscribe(IncidentTouched, lambda m: heard.append(("second", m.incident_ids)))

    await bus.publish(IncidentTouched(("inc-0001",), None))

    assert heard == [("first", ("inc-0001",)), ("second", ("inc-0001",))]


async def test_a_subscriber_of_another_type_hears_nothing():
    bus, heard = Bus(), []
    bus.subscribe(IncidentClosed, heard.append)

    await bus.publish(IncidentTouched(("inc-0001",), None))

    assert heard == []


async def test_a_failing_handler_does_not_stop_the_others(caplog):
    bus, heard = Bus(), []

    def broken(message):
        raise RuntimeError("boom")

    bus.subscribe(IncidentTouched, broken)
    bus.subscribe(IncidentTouched, heard.append)

    with caplog.at_level(logging.ERROR, logger="brain.mind"):
        await bus.publish(IncidentTouched(("inc-0001",), None))

    assert len(heard) == 1
    assert "boom" in caplog.text


async def test_sync_and_async_handlers_both_work():
    bus, heard = Bus(), []

    async def later(message):
        heard.append("async")

    bus.subscribe(IncidentClosed, later)
    bus.subscribe(IncidentClosed, lambda m: heard.append("sync"))

    await bus.publish(IncidentClosed("inc-0001", "apprehended", None))

    assert heard == ["async", "sync"]
