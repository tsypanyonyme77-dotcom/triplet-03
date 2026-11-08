"""Security claims written as tests, so they stay true: the build fails when one stops holding."""

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).parents[1] / "src" / "brain"
FILES = [p for p in SRC.rglob("*.py")]


def parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text())


def calls(tree: ast.AST):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)]


def test_only_the_gate_calls_the_twin_actuator():
    offenders = []
    for path in FILES:
        for call in calls(parse(path)):
            if isinstance(call.func, ast.Attribute) and call.func.attr == "call_actuator" and path.relative_to(SRC).as_posix() not in ("gate/__init__.py", "journal.py", "adapters/twin_mcp.py", "adapters/guardian_v1.py"):
                offenders.append(f"{path.relative_to(SRC)}:{call.lineno}")

    assert offenders == [], "call_actuator outside the gate (journal.py and the adapter only wrap or define it): " + ", ".join(offenders)


def test_a_brain_namespace_event_is_made_only_by_the_timeline_and_the_api_broadcaster():
    allowed = {"timeline.py", "api/__init__.py"}
    offenders = []
    for path in FILES:
        if path.relative_to(SRC).as_posix() in allowed:
            continue
        for call in calls(parse(path)):
            name = getattr(call.func, "id", getattr(call.func, "attr", ""))
            if name == "TimelineEvent" and any(isinstance(k.value, ast.Constant) and str(k.value.value).startswith("brain.") for k in call.keywords):
                offenders.append(f"{path.relative_to(SRC)}:{call.lineno}")

    assert offenders == [], ", ".join(offenders)


SECRETISH = re.compile(r"secret|token|hmac|password", re.I)  # signatures are checked in contracts/signing.py, which the next test pins


def test_every_secret_comparison_uses_compare_digest():
    offenders = []
    for path in FILES:
        for node in ast.walk(parse(path)):
            if isinstance(node, ast.Compare) and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
                sides = [node.left, *node.comparators]
                names = [ast.unparse(s) for s in sides]
                constant_side = any(isinstance(s, ast.Constant) for s in sides)
                if not constant_side and any(SECRETISH.search(n) for n in names) and not any("hash" in n or "_env" in n or "signed_by" in n for n in names):
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: {ast.unparse(node)}")

    assert offenders == [], "\n".join(offenders)


DANGEROUS = {"eval", "exec", "compile", "__import__"}


def test_no_eval_exec_pickle_shell_or_disabled_certificate_checks():
    offenders = []
    for path in FILES:
        tree = parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] in ("pickle", "marshal", "shelve") for a in node.names):
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: imports pickle")
        for call in calls(tree):
            if isinstance(call.func, ast.Name) and call.func.id in DANGEROUS:
                offenders.append(f"{path.relative_to(SRC)}:{call.lineno}: {call.func.id}()")
            for keyword in call.keywords:
                if (keyword.arg == "shell" and getattr(keyword.value, "value", False) is True) or (keyword.arg == "verify" and getattr(keyword.value, "value", True) is False):
                    offenders.append(f"{path.relative_to(SRC)}:{call.lineno}: {keyword.arg}")
            if isinstance(call.func, ast.Attribute) and call.func.attr == "load" and isinstance(call.func.value, ast.Name) and call.func.value.id == "yaml":
                offenders.append(f"{path.relative_to(SRC)}:{call.lineno}: yaml.load")

    assert offenders == [], "\n".join(offenders)


def test_scenario_ids_and_schema_names_must_match_a_plain_pattern(tmp_path):
    from brain.scenario import load_raw_scenario

    for hostile in ("../config/partners", "..%2Fconfig", "b2/../../x", "b2\x00", "", "a" * 200):
        with pytest.raises((FileNotFoundError, ValueError)):
            load_raw_scenario(hostile)


def test_a_request_with_a_traversal_name_is_404_or_422():
    import httpx

    from brain.api import Hub, create_app
    from brain.config import ModelsConfig, PartnersConfig, Policy

    hub = Hub(PartnersConfig(), Policy(), ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}}), mocks="inproc")

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
            return [(await client.get(f"/schemas/{name}")).status_code for name in ("..%2F..%2Fconfig%2Fpartners", "..%252F..", "a%00b")]

    import asyncio

    assert all(code in (404, 422) for code in asyncio.run(go()))


def test_the_signature_check_uses_compare_digest():
    source = (SRC / "contracts" / "signing.py").read_text()

    assert "hmac.compare_digest" in source


def test_a_scenario_id_with_a_dot_or_slash_is_refused_before_any_file_is_looked_for():
    from brain.scenario import load_raw_scenario

    with pytest.raises(FileNotFoundError, match="letters, digits"):
        load_raw_scenario("../scenarios/b2")
