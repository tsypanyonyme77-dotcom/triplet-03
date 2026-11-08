"""TLS and mutual TLS: the listener serves https, refuses a client with no certificate or the wrong authority's, and the adapters connect with the CA and a client certificate."""

import asyncio
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from brain.adapters.tls import client_context, guardian_client, twin_target, uvicorn_options
from brain.config import TlsConfig

ROOT = Path(__file__).parents[1]


def make_certs(folder: Path) -> Path:
    subprocess.run([str(ROOT / "scripts/make_certs.sh")], check=True, env={"CERTS_DIR": str(folder), "PATH": "/usr/bin:/bin"}, capture_output=True)
    return folder


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Running:
    """A uvicorn server in a thread, so a test can talk to it over a real socket."""

    def __init__(self, app, tls: TlsConfig | None) -> None:
        self.port = free_port()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="critical", **uvicorn_options(tls)))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("server did not start")

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(5)


APP = Starlette(routes=[Route("/", lambda request: JSONResponse({"ok": True}))])


@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    return make_certs(tmp_path_factory.mktemp("certs"))


def get(url, ca=None, cert=None):
    """A request that trusts `ca` (a file) and presents `cert` (a name in the same folder) the way the adapters do."""
    tls = TlsConfig(ca=ca, cert=cert and f"{cert}.pem", key=cert and f"{cert}.key")
    return httpx.get(url, timeout=5, verify=client_context(tls))


def test_the_brain_serves_https_with_the_configured_certificate(certs):
    with Running(APP, TlsConfig(cert=str(certs / "brain.pem"), key=str(certs / "brain.key"))) as run:
        assert get(f"https://localhost:{run.port}/", ca=str(certs / "ca.pem")).json() == {"ok": True}
        with pytest.raises(httpx.ConnectError):
            get(f"https://localhost:{run.port}/")  # a client that does not trust our authority refuses the server


def test_a_client_that_does_not_present_a_certificate_is_refused_when_mutual_tls_is_on(certs):
    tls = TlsConfig(cert=str(certs / "brain.pem"), key=str(certs / "brain.key"), ca=str(certs / "ca.pem"))
    with Running(APP, tls) as run:
        url, ca = f"https://localhost:{run.port}/", str(certs / "ca.pem")
        with pytest.raises(httpx.HTTPError):
            get(url, ca=ca)
        assert get(url, ca=ca, cert=str(certs / "twin")).status_code == 200


def test_the_brain_refuses_a_partner_whose_certificate_the_ca_did_not_sign(certs, tmp_path):
    other = make_certs(tmp_path / "other")
    tls = TlsConfig(cert=str(certs / "brain.pem"), key=str(certs / "brain.key"), ca=str(certs / "ca.pem"))
    with Running(APP, tls) as run:
        with pytest.raises(httpx.HTTPError):
            get(f"https://localhost:{run.port}/", ca=str(certs / "ca.pem"), cert=str(other / "twin"))


def test_the_guardian_client_presents_its_certificate_and_trusts_only_the_ca(certs):
    tls = TlsConfig(cert=str(certs / "brain.pem"), key=str(certs / "brain.key"), ca=str(certs / "ca.pem"))
    client_tls = TlsConfig(ca=str(certs / "ca.pem"), cert=str(certs / "guardian.pem"), key=str(certs / "guardian.key"))

    async def call(port):
        async with guardian_client(f"https://localhost:{port}", client_tls) as client:
            return (await client.get("/")).json()

    with Running(APP, tls) as run:
        assert asyncio.run(call(run.port)) == {"ok": True}


def test_the_mcp_client_connects_over_https_with_the_ca_and_a_client_certificate(certs):
    from brain.adapters.twin_mcp import McpTwinAdapter
    from mocks.twin.engine import MockTwin
    from mocks.twin.server import build_server

    tls = TlsConfig(cert=str(certs / "brain.pem"), key=str(certs / "brain.key"), ca=str(certs / "ca.pem"))
    client_tls = TlsConfig(ca=str(certs / "ca.pem"), cert=str(certs / "twin.pem"), key=str(certs / "twin.key"))
    app = build_server(MockTwin()).streamable_http_app(streamable_http_path="/mcp")

    async def call(port):
        async with McpTwinAdapter(twin_target(f"https://localhost:{port}/mcp", client_tls)) as twin:
            return await twin.call_tool("list_readings")

    with Running(app, tls) as run:
        assert "readings" in asyncio.run(call(run.port))


def test_plain_urls_and_missing_settings_change_nothing():
    assert twin_target("http://localhost:8765/mcp", TlsConfig(ca="x")) == "http://localhost:8765/mcp"
    assert twin_target("https://twin/mcp", None) == "https://twin/mcp" and uvicorn_options(None) == {}
