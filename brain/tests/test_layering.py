"""The separation the Phase 1 jury looks for: decision logic never imports a partner protocol, and an adapter imports nothing of the logic."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "brain"
WIRING = ("adapters/", "api/", "commands/", "scenario.py")  # the only places that may name an adapter
ADAPTER_MAY_IMPORT = {"brain.adapters", "brain.config", "brain.contracts", "brain.ports"}


def _imports(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)  # `from brain import adapters`
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return {m for m in out if m.startswith("brain")}


def _under(module: str, allowed: set[str]) -> bool:
    return any(module == a or module.startswith(a + ".") for a in allowed)


def test_only_wiring_imports_an_adapter():
    offenders = [str(p.relative_to(SRC)) for p in SRC.rglob("*.py")
                 if not str(p.relative_to(SRC)).startswith(WIRING) and any(_under(m, {"brain.adapters"}) for m in _imports(p))]
    assert offenders == [], f"logic modules import a partner adapter: {offenders}"


def test_an_adapter_imports_only_contracts_ports_and_config():
    offenders = {str(p.relative_to(SRC)): sorted(m for m in _imports(p) if not _under(m, ADAPTER_MAY_IMPORT))
                 for p in (SRC / "adapters").glob("*.py")}
    assert {k: v for k, v in offenders.items() if v} == {}
