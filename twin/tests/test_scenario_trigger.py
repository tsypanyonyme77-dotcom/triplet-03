"""The one-command trigger, against a small stand-in Twin on a real socket (the script uses only the standard library)."""
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

TRIGGER = Path(__file__).resolve().parents[1] / "scenarios" / "trigger.py"


def _trigger(url):
    spec = importlib.util.spec_from_file_location("trigger", TRIGGER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.TWIN_URL, module.POLL_S = url, 0.01
    return module


@pytest.fixture
def twin():
    state = {"result": "PASS", "refuse": False, "headers": []}

    class Handler(BaseHTTPRequestHandler):
        def _answer(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # noqa: N802 (http.server's name)
            state["headers"].append(self.headers.get("X-Operator-Key"))
            state["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if state["refuse"]:
                return self._answer(409, {"detail": "t2 is still running"})
            self._answer(202, {"name": "A scenario", "started_at": "2026-11-08T10:00:00.000Z"})

        def do_GET(self):  # noqa: N802
            self._answer(200, {"current": None, "last": {"id": "t1", "result": state["result"], "log": "t1-x.log",
                                                         "finished_at": "2026-11-08T10:01:00.000Z", "checks": []}})

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield state, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_a_pass_exits_0_and_names_the_log(twin, capsys):
    state, url = twin
    assert _trigger(url).run("t1", brain="operator", seed=3) == 0
    assert "logs/t1-x.log" in capsys.readouterr().out
    assert state["body"] == {"brain": "operator", "seed": 3}
    assert state["headers"] == ["dev-only-operator-key"]


def test_a_failed_scenario_exits_1(twin):
    state, url = twin
    state["result"] = "FAIL"
    assert _trigger(url).run("t1") == 1


def test_a_refusal_and_an_unreachable_twin_say_so(twin, capsys):
    state, url = twin
    state["refuse"] = True
    assert _trigger(url).run("t1") == 2
    assert "still running" in capsys.readouterr().err
    assert _trigger("http://127.0.0.1:9").run("t1") == 2
    assert "docker compose up" in capsys.readouterr().err
