"""A knowledge graph of the City Brain codebase, built from the code itself.

    uv run python docs/codebase/graph.py              # rebuild graph.json and CODEBASE.md
    uv run python docs/codebase/graph.py check        # exit 1 if they are out of date
    uv run python docs/codebase/graph.py query gate   # a node and everything linked to it

Nodes: modules, classes, methods, functions, timeline events, CLI commands, HTTP
endpoints, MCP tools, config files and models, reflex rules, playbook items, scenarios
and tests. Edges: imports, defines, emits, handles (the screen), checks (tests and
scenario expectations), serves, loads. Everything is read with `ast`, YAML and JSON:
nothing is imported or run, so the graph builds even when the code is broken.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent  # brain/
OUT_JSON, OUT_MD = HERE / "graph.json", HERE / "CODEBASE.md"
SOURCES = {"src/brain": "brain", "mocks": "mocks", "tests": "tests"}
EVENT = re.compile(r"^brain\.[a-z_]+(\.[a-z_]+)+$")  # how an event name looks in tests and scenarios
EMITTED = re.compile(r"^brain\.[a-z_]+(\.[a-z_]+)*$")  # an emit call may also send a one-word event (brain.started)
CONFIG_FILES = {"partners": "PartnersConfig", "policy": "Policy", "models": "ModelsConfig"}


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: set[tuple[str, str, str, str]] = set()  # (source, label, target, where)

    def node(self, node_id: str, kind: str, **attrs) -> str:
        entry = self.nodes.setdefault(node_id, {"id": node_id, "kind": kind})
        entry.update({k: v for k, v in attrs.items() if v not in (None, "", [])})
        return node_id

    def edge(self, source: str, label: str, target: str, where: str = "") -> None:
        self.edges.add((source, label, target, where))


def first_line(doc: str | None) -> str:
    return (doc or "").strip().split("\n\n")[0].replace("\n", " ").strip()


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT)
    for folder, package in SOURCES.items():
        if rel.is_relative_to(folder):
            parts = list(rel.relative_to(folder).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            return ".".join([package, *parts])
    return ".".join(rel.with_suffix("").parts)


def where(path: Path, line: int) -> str:
    return f"{path.relative_to(ROOT)}:{line}"


def signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [a.arg for a in fn.args.posonlyargs + fn.args.args if a.arg not in ("self", "cls")]
    args += [f"*{fn.args.vararg.arg}"] if fn.args.vararg else []
    args += [a.arg for a in fn.args.kwonlyargs]
    return f"{'async ' if isinstance(fn, ast.AsyncFunctionDef) else ''}{fn.name}({', '.join(args)})"


# --------------------------------------------------------------------------- python


def scan_python(g: Graph, files: list[Path], modules: set[str]) -> None:
    for path in files:
        name = module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        mod = g.node(f"module:{name}", "module", path=str(path.relative_to(ROOT)), summary=first_line(ast.get_docstring(tree)),
                     lines=len(path.read_text(encoding="utf-8").splitlines()))
        # A module docstring may list its routes: "    GET  /events     what it does".
        routes = {f"{m} {p}": d for m, p, d in re.findall(r"^\s+(GET|POST)\s+(\S+)\s{2,}(\S.*)$", ast.get_docstring(tree) or "", re.M)}

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                cls = g.node(f"class:{name}.{node.name}", "class", where=where(path, node.lineno),
                             summary=first_line(ast.get_docstring(node)),
                             bases=[ast.unparse(b) for b in node.bases])
                g.edge(mod, "defines", cls)
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not (item.name.startswith("__") and item.name != "__init__"):
                        method = g.node(f"method:{name}.{node.name}.{item.name}", "method", where=where(path, item.lineno),
                                        signature=signature(item), summary=first_line(ast.get_docstring(item)))
                        g.edge(cls, "defines", method)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "test" if name.startswith("tests.") and node.name.startswith("test_") else "function"
                fn = g.node(f"{kind}:{name}.{node.name}", kind, where=where(path, node.lineno), signature=signature(node),
                            summary=first_line(ast.get_docstring(node)))
                g.edge(mod, "defines", fn)

        for node in ast.walk(tree):
            # Imports between our own modules.
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom):
                if node.level:  # relative: tests import each other this way
                    base = name.split(".")[: -node.level] if not path.name == "__init__.py" else name.split(".")[: len(name.split(".")) - node.level + 1]
                    targets = [".".join(base + ([node.module] if node.module else []))]
                elif node.module:
                    # `from brain import config` imports the module brain.config, not the package itself.
                    submodules = [f"{node.module}.{a.name}" for a in node.names if f"{node.module}.{a.name}" in modules]
                    targets = submodules if submodules else [node.module]
            elif isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            for target in targets:
                if target in modules and target != name:
                    g.edge(mod, "imports", f"module:{target}")

            # Timeline events: emit("brain....") and TimelineEvent(type="brain....").
            if isinstance(node, ast.Call):
                sent = None
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "emit" and node.args:
                    sent = node.args[0]
                elif isinstance(func, ast.Name) and func.id == "TimelineEvent":
                    sent = next((kw.value for kw in node.keywords if kw.arg == "type"), None)
                # `"brain.plan.verified" if ok else "brain.plan.rejected"` sends either name.
                names = [c.value for c in ast.walk(sent) if isinstance(c, ast.Constant) and isinstance(c.value, str)] if sent else []
                for event in names:
                    if (EVENT if name.startswith("tests.") else EMITTED).match(event):
                        g.node(f"event:{event}", "event")
                        label = "checks" if name.startswith("tests.") else "emits"
                        g.edge(mod, label, f"event:{event}", where(path, node.lineno))

            # Event names a test asserts on.
            if name.startswith("tests.") and isinstance(node, ast.Constant) and isinstance(node.value, str) and EVENT.match(node.value):
                g.node(f"event:{node.value}", "event")
                g.edge(mod, "checks", f"event:{node.value}")

            # Which config file is loaded into which model.
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name)):
                called = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
                if called == "load" and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value in CONFIG_FILES:
                    g.edge(mod, "loads", f"config:config/{node.args[1].value}.yaml", where(path, node.lineno))

            # Entry points.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in node.decorator_list:
                    if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute):
                        verb = deco.func.attr
                        if verb in ("get", "post", "put", "delete") and deco.args and isinstance(deco.args[0], ast.Constant):
                            app = "Brain API" if name.startswith("brain.") else "mock Guardian"
                            route = f"{verb.upper()} {deco.args[0].value}"
                            ep = g.node(f"endpoint:{route}", "endpoint", served_by=app, where=where(path, node.lineno),
                                        summary=first_line(ast.get_docstring(node)) or routes.get(route, ""))
                            g.edge(mod, "serves", ep)
                        if verb == "tool":
                            tool = g.node(f"mcp_tool:{node.name}", "mcp_tool", served_by="mock Twin", where=where(path, node.lineno),
                                          summary=first_line(ast.get_docstring(node)))
                            g.edge(mod, "serves", tool)

        if name == "brain.cli":
            scan_cli(g, tree, path, mod)


def scan_cli(g: Graph, tree: ast.Module, path: Path, mod: str) -> None:
    """`commands.add_parser("x", ...)` followed by `x.set_defaults(handler=cmd_x)`."""
    parsers: dict[str, tuple[str, int, str]] = {}
    owners: dict[str, str] = {}  # subparsers variable -> the parser it belongs to (`audit verify`)
    for node in ast.walk(tree):  # ast.walk goes breadth-first, but these assignments sit in one function body, in order
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
            call, target = node.value, node.targets[0]
            if not isinstance(target, ast.Name) or not isinstance(call.func.value, ast.Name):
                continue
            if call.func.attr == "add_subparsers":
                owners[target.id] = call.func.value.id
            elif call.func.attr == "add_parser" and call.args:
                helptext = next((kw.value.value for kw in call.keywords if kw.arg == "help" and isinstance(kw.value, ast.Constant)), "")
                parent = parsers.get(owners.get(call.func.value.id, ""), ("",))[0]
                parsers[target.id] = (f"{parent} {call.args[0].value}".strip(), node.lineno, helptext)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "set_defaults":
            owner = node.func.value.id if isinstance(node.func.value, ast.Name) else None
            handler = next((ast.unparse(kw.value) for kw in node.keywords if kw.arg == "handler"), None)
            if owner in parsers:
                command, line, helptext = parsers[owner]
                cli = g.node(f"cli:brain {command}", "cli_command", where=where(path, line), handler=handler, summary=helptext)
                g.edge(mod, "serves", cli)
                if handler:
                    g.edge(cli, "runs", f"function:brain.cli.{handler}")


# --------------------------------------------------------------------------- data files


def scan_data(g: Graph) -> None:
    for file_name, model in CONFIG_FILES.items():
        path = ROOT / "config" / f"{file_name}.yaml"
        cfg = g.node(f"config:config/{file_name}.yaml", "config_file", path=str(path.relative_to(ROOT)),
                     summary=first_line(path.read_text().splitlines()[0].lstrip("# ")))
        g.edge(cfg, "validated_by", f"class:brain.config.{model}")

    for rules_file in sorted((ROOT / "src/brain/departments/rules").glob("*.yaml")):
        for rule in yaml.safe_load(rules_file.read_text())["rules"]:
            rid = g.node(f"rule:{rule['id']}", "rule", name=rule["name"], scope=rule.get("scope", "assessment"),
                         summary=first_line(rule.get("description", "")), where=str(rules_file.relative_to(ROOT)),
                         actions=[d["action"] for d in rule["do"]])
            g.edge("module:brain.departments", "loads", rid)

    playbook = yaml.safe_load((ROOT / "src/brain/departments/playbooks/police.yaml").read_text())["items"]
    for item in playbook:
        g.node(f"playbook:{item['id']}", "playbook_item", summary=item["title"], where="src/brain/departments/playbooks/police.yaml")
        g.edge("module:brain.knowledge", "loads", f"playbook:{item['id']}")

    for path in sorted((ROOT / "scenarios").glob("b*.json"), key=lambda p: int(p.stem[1:])):
        scenario = json.loads(path.read_text())
        sid = g.node(f"scenario:{scenario['id']}", "scenario", name=scenario.get("name"), path=str(path.relative_to(ROOT)),
                     summary=scenario.get("expected_brain", ""))
        expect = scenario.get("expect", {})
        names = set()
        for section in (expect, expect.get("scripted_team", {})):
            for chain in section.get("events_in_order", []):
                names.update(chain)
            names.update(section.get("forbidden_events", []))
            names.update(section.get("event_counts", {}))
        for event in sorted(n for n in names if EVENT.match(n)):
            g.node(f"event:{event}", "event")
            g.edge(sid, "checks", f"event:{event}")

    screen = ROOT / "src/brain/api/static/index.html"
    for match in sorted(set(re.findall(r'case "(brain\.[a-z_.]+)"', screen.read_text()))):
        g.node(f"event:{match}", "event")
        g.edge("screen:index.html", "handles", f"event:{match}")
    g.node("screen:index.html", "screen", path=str(screen.relative_to(ROOT)), summary="The Strip Board timeline screen (one static page)")


# --------------------------------------------------------------------------- build


def build() -> Graph:
    g = Graph()
    files = sorted(p for folder in SOURCES for p in (ROOT / folder).rglob("*.py") if "__pycache__" not in p.parts)
    modules = {module_name(p) for p in files}
    scan_python(g, files, modules)
    scan_data(g)
    g.edges = {e for e in g.edges if e[0] in g.nodes and e[2] in g.nodes}  # drop links to nodes never defined
    return g


def as_json(g: Graph) -> str:
    edges = [{"source": s, "label": l, "target": t, **({"where": w} if w else {})} for s, l, t, w in sorted(g.edges)]
    return json.dumps({"nodes": sorted(g.nodes.values(), key=lambda n: n["id"]), "edges": edges}, indent=1, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- CODEBASE.md


def package_of(module: str) -> str:
    parts = module.split(".")
    return ".".join(parts[:2]) if parts[0] in ("brain", "mocks") and len(parts) > 1 else parts[0]


def as_markdown(g: Graph) -> str:
    n, out = g.nodes, []
    by_kind = defaultdict(list)
    for node in n.values():
        by_kind[node["kind"]].append(node)
    edges_from, edges_to = defaultdict(list), defaultdict(list)
    for s, label, t, w in sorted(g.edges):
        edges_from[s].append((label, t, w))
        edges_to[t].append((label, s, w))

    def link(node_id: str) -> str:
        node = n[node_id]
        return f"`{node.get('where') or node.get('path') or node_id}`"

    out.append("# City Brain codebase map\n")
    out.append("Generated from the code by `docs/codebase/graph.py`; rebuild it after moving or adding modules, events, "
               "endpoints, rules or scenarios (`uv run python docs/codebase/graph.py`, then `... graph.py check` passes). "
               "The same graph, with every edge, is in `graph.json`; `uv run python docs/codebase/graph.py query <word>` "
               "prints any node and its links. Paths are relative to `brain/`.\n")

    # Package dependencies.
    out.append("## Package dependencies\n")
    out.append("An arrow means \"imports\". Tests and the CLI are left out to keep the picture readable.\n")
    pairs = set()
    for s, label, t, _ in g.edges:
        if label == "imports" and s.startswith("module:") and t.startswith("module:"):
            a, b = package_of(s[7:]), package_of(t[7:])
            if a != b and not a.startswith("tests") and a not in ("brain.cli",):
                pairs.add((a, b))
    out.append("```mermaid\nflowchart LR")
    for a, b in sorted(pairs):
        out.append(f"  {a.replace('.', '_')}[{a}] --> {b.replace('.', '_')}[{b}]")
    out.append("```\n")

    # Modules.
    out.append("## Modules\n")
    groups = defaultdict(list)
    for module in sorted(by_kind["module"], key=lambda m: m["id"]):
        groups[package_of(module["id"][7:])].append(module)
    for package in sorted(groups, key=lambda p: (p.startswith("tests"), p.startswith("mocks"), p)):
        if package.startswith("tests"):
            continue
        out.append(f"### {package}\n")
        for module in groups[package]:
            mid = module["id"]
            out.append(f"- **`{module['path']}`** ({module['lines']} lines): {module.get('summary', '')}")
            for label, target, _ in edges_from[mid]:
                if label != "defines":
                    continue
                child = n[target]
                note = f": {child['summary']}" if child.get("summary") else ""
                if child["kind"] == "class":
                    methods = [n[m] for lab, m, _ in edges_from[target] if lab == "defines"]
                    names = ", ".join(f"`{m['id'].rsplit('.', 1)[1]}`" for m in methods)
                    out.append(f"    - class `{target.rsplit('.', 1)[1]}` `{child['where']}`{note}" + (f" Methods: {names}." if names else ""))
                elif child["kind"] == "function" and not target.rsplit(".", 1)[1].startswith("_"):
                    out.append(f"    - `{child['signature']}` `{child['where']}`{note}")
        out.append("")

    # Entry points.
    out.append("## Entry points\n")
    out.append("| Kind | Name | Where | What |\n| --- | --- | --- | --- |")
    for kind, title in (("cli_command", "CLI"), ("endpoint", "HTTP"), ("mcp_tool", "MCP tool (mock Twin)")):
        for node in sorted(by_kind[kind], key=lambda x: x["id"]):
            served = f" ({node['served_by']})" if node.get("served_by") and kind == "endpoint" else ""
            out.append(f"| {title}{served} | `{node['id'].split(':', 1)[1]}` | `{node['where']}` | {node.get('summary', '')} |")
    out.append("")

    # Events.
    out.append("## Timeline events\n")
    out.append("Every event the Brain emits, where it is emitted, whether the screen draws it, and which tests and "
               "scenarios assert on it.\n")
    out.append("| Event | Emitted at | Screen | Checked by |\n| --- | --- | --- | --- |")
    for event in sorted(by_kind["event"], key=lambda x: x["id"]):
        eid = event["id"]
        emitted = sorted({w for lab, s, w in edges_to[eid] if lab == "emits" and w})
        shown = "yes" if any(lab == "handles" for lab, _, _ in edges_to[eid]) else ""
        checkers = sorted({s.split(":", 1)[1].removeprefix("tests.") for lab, s, _ in edges_to[eid] if lab == "checks"})
        out.append(f"| `{eid[6:]}` | {', '.join(f'`{w}`' for w in emitted) or 'not emitted'} | {shown} | {', '.join(checkers)} |")
    out.append("")

    # Rules and playbook.
    out.append("## Reflex rules and playbook\n")
    out.append("| Rule | Scope | Does | Description |\n| --- | --- | --- | --- |")
    for rule in sorted(by_kind["rule"], key=lambda x: x["id"]):
        out.append(f"| `{rule['id'][5:]}` {rule['name']} | {rule['scope']} | {', '.join(rule['actions'])} | {rule.get('summary', '')} |")
    out.append("")
    out.append("Playbook items (`src/brain/departments/playbooks/police.yaml`): " +
               "; ".join(f"`{p['id'][9:]}` {p['summary']}" for p in sorted(by_kind["playbook_item"], key=lambda x: x["id"])) + ".\n")

    # Config.
    out.append("## Configuration\n")
    out.append("Each file must equal its model's defaults (a test checks this): change both together.\n")
    for cfg in sorted(by_kind["config_file"], key=lambda x: x["id"]):
        model = next((t for lab, t, _ in edges_from[cfg["id"]] if lab == "validated_by"), "")
        loaders = sorted({s[7:] for lab, s, _ in edges_to[cfg["id"]] if lab == "loads"})
        out.append(f"- `{cfg['path']}` → `{model.split(':', 1)[1]}` ({n[model]['where'] if model in n else ''}); loaded by {', '.join(f'`{m}`' for m in loaders)}")
    out.append("")

    # Scenarios.
    out.append("## Test Book scenarios\n")
    out.append("| Id | Name | What the Brain must do |\n| --- | --- | --- |")
    for sc in sorted(by_kind["scenario"], key=lambda x: int(x["id"].split(":b")[1])):
        out.append(f"| `{sc['id'][9:]}` | {sc.get('name', '')} | {sc.get('summary', '')} |")
    out.append("")

    # Tests.
    out.append("## Tests\n")
    out.append("Test names state the behaviour they pin down; read them as the specification of each module.\n")
    for module in sorted((m for m in by_kind["module"] if m["id"].startswith("module:tests.")), key=lambda m: m["id"]):
        mid = module["id"]
        covers = sorted({t[7:] for lab, t, _ in edges_from[mid] if lab == "imports" and not t.startswith("module:tests")})
        tests = [n[t] for lab, t, _ in edges_from[mid] if lab == "defines" and n[t]["kind"] == "test"]
        if not tests:
            continue
        out.append(f"### `{module['path']}` ({len(tests)} tests)\n")
        if module.get("summary"):
            out.append(module["summary"] + "\n")
        if covers:
            out.append("Imports: " + ", ".join(f"`{c}`" for c in covers) + "\n")
        for test in tests:
            out.append(f"- `{test['id'].rsplit('.', 1)[1]}` `{test['where']}`")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- commands


def query(g: Graph, word: str) -> None:
    word = word.lower()
    hits = [node for node in g.nodes.values() if word in node["id"].lower() or word in node.get("summary", "").lower()]
    if not hits:
        print(f"nothing matches {word!r}")
        return
    for node in sorted(hits, key=lambda x: (x["kind"] != "module", x["id"]))[:25]:
        details = {k: v for k, v in node.items() if k not in ("id", "kind")}
        print(f"{node['id']}  [{node['kind']}]  {json.dumps(details, ensure_ascii=False)}")
        for s, label, t, w in sorted(g.edges):
            if s == node["id"] and label != "defines":
                print(f"    → {label} {t}" + (f"  ({w})" if w else ""))
            elif t == node["id"]:
                print(f"    ← {label} {s}" + (f"  ({w})" if w else ""))
    if len(hits) > 25:
        print(f"... {len(hits) - 25} more; narrow the word")


def main(argv: list[str]) -> int:
    g = build()
    text_json, text_md = as_json(g), as_markdown(g)
    command = argv[0] if argv else "build"
    if command == "query" and len(argv) > 1:
        query(g, argv[1])
        return 0
    if command == "check":
        stale = [p.name for p, text in ((OUT_JSON, text_json), (OUT_MD, text_md)) if not p.exists() or p.read_text() != text]
        print("up to date" if not stale else f"out of date: {', '.join(stale)}; run uv run python docs/codebase/graph.py")
        return 1 if stale else 0
    OUT_JSON.write_text(text_json, encoding="utf-8")
    OUT_MD.write_text(text_md, encoding="utf-8")
    kinds = defaultdict(int)
    for node in g.nodes.values():
        kinds[node["kind"]] += 1
    print(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}: {len(g.nodes)} nodes "
          f"({', '.join(f'{v} {k}' for k, v in sorted(kinds.items()))}), {len(g.edges)} edges")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
