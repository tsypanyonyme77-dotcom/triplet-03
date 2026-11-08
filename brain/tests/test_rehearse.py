"""The rehearsal: everything the freeze needs, run offline, in one command, with a report."""

from brain import rehearse as rehearsal


async def test_rehearsal_passes_offline_and_writes_a_report(tmp_path):
    report = await rehearsal.rehearse(tmp_path, quick=True, screens=False)

    assert report.passed, [s for s in report.steps if not s.passed]
    names = [s.name for s in report.steps]
    assert names == ["Test Book", "Baselines", "Temporal promises", "Held-out variants", "Forward-model benchmark", "Team under faults",
                     "Learning curve", "Ablations", "Poisoned lesson", "Offline"]
    text = next(tmp_path.glob("*.md")).read_text()
    assert "PASS" in text and "FAIL" not in text and "| configuration |" in text and "team runs" in text
    assert next(tmp_path.glob("*.json")).exists()


async def test_a_failing_step_fails_the_rehearsal(tmp_path, monkeypatch):
    async def broken(context):
        return rehearsal.Step("Broken", False, "on purpose")

    monkeypatch.setattr(rehearsal, "STEPS", [broken])

    report = await rehearsal.rehearse(tmp_path, quick=True, screens=False)

    assert not report.passed and "FAIL" in next(tmp_path.glob("*.md")).read_text()


async def test_a_step_that_raises_is_a_failed_step_not_a_crash(tmp_path, monkeypatch):
    async def explodes(context):
        raise RuntimeError("boom")

    monkeypatch.setattr(rehearsal, "STEPS", [explodes])

    report = await rehearsal.rehearse(tmp_path, quick=True, screens=False)

    assert not report.passed and "boom" in report.steps[0].detail


async def test_a_step_that_reaches_for_the_network_fails_the_offline_check(tmp_path, monkeypatch):
    import socket

    async def reaches_out(context):
        try:
            socket.create_connection(("203.0.113.1", 80), timeout=0.2)
        except OSError:
            pass
        return rehearsal.Step("Reaches out", True, "")

    monkeypatch.setattr(rehearsal, "STEPS", [reaches_out, rehearsal.offline_step])

    report = await rehearsal.rehearse(tmp_path, quick=True, screens=False)

    assert report.steps[-1].name == "Offline" and not report.steps[-1].passed
