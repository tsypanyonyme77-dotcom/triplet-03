"""Who may call the Brain's API, and what the edge refuses before any route runs.

Off loopback every route needs a token, and a token carries one scope: `read` (the GET routes and the live stream), `analyse`,
`push` (a partner putting its own events on the timeline), `approve` and `admin` (running scenarios, sleep). A partner's push
token also names the partner, so an event it pushes takes its source from the token, never from the body. On loopback with
`require: auto` nothing is required, so the scenarios and tests run as before. The checks that hold either way live here too:
a body size limit, a per-caller rate limit and the security headers.

Tokens come from environment variables and are compared in constant time. They are never written to an event, a log or a reply.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.responses import JSONResponse

from brain.config import SecurityConfig

PUBLIC = ("/", "/health", "/schemas", "/.well-known/agent-card.json", "/.well-known/jwks.json", "/canopy3d.js", "/brainshell.js", "/api/login", "/api/logout")
PUBLIC_PREFIXES = ("/schemas/", "/vendor/", "/static/", "/docs", "/openapi.json")
CSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self' data:"


AUDIENCE = "city-brain"


def _b64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def mint_token(key: str, sub: str, scopes: list[str], ttl_s: int) -> tuple[str, str]:
    """A signed token (HS256 JWT) for `sub`, good for `ttl_s` seconds. Returns (token, its id, for revoking)."""
    jti = uuid.uuid4().hex[:12]
    head = _b64e(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64e(json.dumps({"sub": sub, "scope": " ".join(scopes), "aud": AUDIENCE, "iat": int(time.time()), "exp": int(time.time()) + ttl_s, "jti": jti}).encode())
    return f"{head}.{body}.{_b64e(hmac.new(key.encode(), f'{head}.{body}'.encode(), 'sha256').digest())}", jti


def scope_for(method: str, path: str) -> str | None:
    """The scope a request needs, `None` for the public list, or `UNCLASSIFIED` for a route nobody has classified (a test fails on it)."""
    if path in PUBLIC or path.startswith(PUBLIC_PREFIXES):
        return None
    if method == "POST" and path in ("/api/events", "/api/retractions"):
        return "push"
    if method == "POST" and path.startswith("/api/approvals"):
        return "approve"
    if method == "POST" and (path in ("/api/sleep", "/api/llm/mode", "/api/llm/check") or path.startswith("/api/scenarios/")):
        return "admin"
    if path == "/mcp" or path.startswith("/mcp/"):  # tools that need more than `read` check the token themselves
        return "read"
    if method == "GET":
        return "read"
    return "UNCLASSIFIED"


@dataclass
class Caller:
    label: str  # `read`, `admin`, ... or a partner name for a push token
    scopes: frozenset[str]


@dataclass
class Security:
    config: SecurityConfig
    _hits: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    @property
    def enabled(self) -> bool:
        return self.config.require == "always"

    def tokens(self) -> list[tuple[str, str, frozenset[str]]]:
        """(label, token, scopes) for every token that is set in the environment."""
        found = []
        for scope, env in self.config.token_envs.items():
            if value := os.environ.get(env):
                found.append((scope, value, frozenset({scope, "read"} if scope in ("analyse", "approve", "admin") else {scope})))
        for partner, env in self.config.push_tokens.items():
            if value := os.environ.get(env):
                found.append((partner, value, frozenset({"push"})))
        return found

    def identify(self, request: Request) -> Caller | None:
        header = request.headers.get("authorization", "")
        presented = header[7:] if header.lower().startswith("bearer ") else request.cookies.get(self.config.cookie_name, "")
        if presented.count(".") == 2:  # a minted, short-lived token
            return self.check_token(presented)
        for label, token, scopes in self.tokens():
            if presented and hmac.compare_digest(presented.encode(), token.encode()):
                return Caller(label, scopes)
        return None

    def check_token(self, token: str) -> Caller | None:
        """A caller from a minted token, or None if it is forged, expired, for another audience, or revoked."""
        key = os.environ.get(self.config.token_key_env)
        try:
            head, body, sig = token.split(".")
            if not key or not hmac.compare_digest(_b64(sig), hmac.new(key.encode(), f"{head}.{body}".encode(), "sha256").digest()):
                return None
            claims = json.loads(_b64(body))
        except (ValueError, KeyError):
            return None
        if claims.get("aud") != AUDIENCE or claims.get("exp", 0) <= time.time() or claims.get("jti") in self.revoked():
            return None
        scopes = frozenset(claims.get("scope", "").split())
        return Caller(str(claims.get("sub", "token")), scopes | ({"read"} if scopes & {"analyse", "approve", "admin"} else set()))

    def revoked(self) -> set[str]:
        path = self.config.revocations_path
        return set(open(path).read().split()) if os.path.exists(path) else set()

    def allows(self, scope: str, headers: dict[str, str]) -> bool:
        """Does the bearer token in these headers carry `scope`? Always true when tokens are not required."""
        if not self.enabled:
            return True
        header = {k.lower(): v for k, v in headers.items()}.get("authorization", "")
        presented = header[7:] if header.lower().startswith("bearer ") else ""
        if presented.count(".") == 2:
            caller = self.check_token(presented)
            return caller is not None and scope in caller.scopes
        return any(presented and hmac.compare_digest(presented.encode(), token.encode()) and scope in scopes for _, token, scopes in self.tokens())

    def limited(self, key: str) -> int | None:
        """Seconds to wait when `key` has used its calls in the last minute, else None."""
        now = time.monotonic()
        hits = [t for t in self._hits[key] if now - t < 60]
        self._hits[key] = hits
        if len(hits) >= self.config.rate_per_minute:
            return max(int(60 - (now - hits[0])) + 1, 1)
        hits.append(now)
        return None


def install(app, security: Security) -> None:
    """Size limit, rate limit, authentication and headers, in that order, for every request."""

    @app.middleware("http")
    async def edge(request: Request, call_next):
        def reply(status: int, body: dict, headers: dict | None = None):
            return JSONResponse(body, status_code=status, headers={**(headers or {})})

        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > security.config.max_body_bytes:
            response = reply(413, {"error": "body_too_large", "limit_bytes": security.config.max_body_bytes})
        else:
            needed = scope_for(request.method, request.url.path)
            caller = security.identify(request) if security.enabled else None
            key = caller.label if caller else (request.client.host if request.client else "anonymous")
            wait = security.limited(key) if security.enabled else None
            if wait is not None:
                response = reply(429, {"error": "rate_limited"}, {"Retry-After": str(wait)})
            elif security.enabled and needed is not None and caller is None:
                response = reply(401, {"error": "authentication_required", "needed": needed}, {"WWW-Authenticate": "Bearer"})
            elif security.enabled and needed is not None and needed not in caller.scopes:
                response = reply(403, {"error": "scope_missing", "needed": needed})
            else:
                request.state.caller = caller
                response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
