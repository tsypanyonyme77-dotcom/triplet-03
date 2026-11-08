"""TLS and mutual TLS for the Brain's two connections and its own listener.

Off loopback, readings and calls should not cross the network in the clear. A `TlsConfig` names a certificate authority to trust (`ca`)
and, for mutual TLS, the certificate and key the Brain presents (`cert`, `key`). The same shape configures the listener, where `ca` is the
authority a connecting client's certificate must come from. Nothing is on by default: loopback and the private Compose network stay plain.
"""

from __future__ import annotations

import ssl
from typing import Any

import httpx

from brain.config import TlsConfig


def client_context(tls: TlsConfig | None) -> ssl.SSLContext:
    """Trust `ca` (or the system's authorities when none is named) and present `cert` and `key` when given."""
    context = ssl.create_default_context(cafile=tls.ca if tls and tls.ca else None)
    if tls and tls.cert and tls.key:
        context.load_cert_chain(tls.cert, tls.key)
    return context


def guardian_client(url: str, tls: TlsConfig | None = None) -> httpx.AsyncClient:
    """The Guardian adapter's HTTP client: verifies the Guardian against `ca`, and presents `cert` when mutual TLS is on."""
    return httpx.AsyncClient(base_url=url, verify=client_context(tls))


def twin_target(url: str, tls: TlsConfig | None = None) -> Any:
    """What `McpTwinAdapter` connects to: the URL as it is, or (for https with TLS settings) a transport that carries them."""
    if not (url.startswith("https") and tls and (tls.ca or tls.cert)):
        return url
    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    return streamable_http_client(url, http_client=httpx2.AsyncClient(verify=client_context(tls)))


def uvicorn_options(tls: TlsConfig | None) -> dict[str, Any]:
    """The `ssl_*` options for the listener. With `ca` set, a client without a certificate from that authority is refused."""
    if not (tls and tls.cert and tls.key):
        return {}
    options: dict[str, Any] = {"ssl_certfile": tls.cert, "ssl_keyfile": tls.key}
    if tls.ca:
        options.update(ssl_ca_certs=tls.ca, ssl_cert_reqs=ssl.CERT_REQUIRED)
    return options
