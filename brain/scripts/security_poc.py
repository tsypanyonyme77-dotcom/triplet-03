"""Proof-of-concept attacks behind docs/SECURITY-MITRE.md section 8. Run from brain/: uv run python scripts/security_poc.py. In process: no network, no model calls."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import tempfile
import time

import httpx

from brain.adapters.guardian_rest import RestGuardianAdapter
from brain.contracts import CONTRACT_VERSION
from brain.contracts.keyring import Key, KeyRing
from brain.contracts.signing import sign
from brain.perception import ContractError, Perception

SECRET = "poc-twin-secret"
OUT = []


def say(id_, title, verdict, detail):
    OUT.append((id_, title, verdict, detail))
    print(f"{id_:5} {verdict:14} {title} :: {detail}")


def reading(**over):
    base = {"contract_version": CONTRACT_VERSION, "sensor_id": "wl-01", "type": "water_level", "zone_id": "zone-01",
            "timestamp": "2026-11-04T10:00:00.000Z", "sequence_no": 1, "value": {"level_m": 1.2, "flow_rate_m3s": 3.0}}
    return {**base, **over}


def ingest(p, raw):
    try:
        p.ingest(raw)
        return "accepted"
    except ContractError as e:
        return f"refused:{e.code}"


# ---- P-A: signature coverage: change one field after signing
def sig_coverage():
    rows = []
    for name, new in [("sensor_id", "wl-02"), ("type", "traffic_camera"), ("zone_id", "zone-09"), ("timestamp", "2026-11-04T11:00:00.000Z"),
                      ("sequence_no", 2), ("value", {"level_m": 9.9, "flow_rate_m3s": 3.0}), ("contract_version", CONTRACT_VERSION),
                      ("department_code", "FIRE"), ("injected_top_level", "x")]:
        p = Perception([CONTRACT_VERSION], SECRET)
        signed = sign(reading(), SECRET, "twin")
        signed[name] = new
        rows.append((name, ingest(p, signed)))
    p = Perception([CONTRACT_VERSION], SECRET)
    signed = sign(reading(), SECRET, "twin")
    signed["trust"] = {"verdict_id": "v-forged", "reading_ref": {"reading_id": "wl-01#1", "sensor_id": "wl-01", "sequence_no": 1}, "status": "trusted", "issued_at": "2026-11-04T10:00:00Z"}
    rows.append(("trust(unsigned field)", ingest(p, signed)))
    say("P-A", "field changed after signing", "see detail", "; ".join(f"{n}={r}" for n, r in rows))


# ---- P-B: stale / withheld readings accepted
def stale():
    p = Perception([CONTRACT_VERSION], SECRET)
    old = sign(reading(timestamp="2020-01-01T00:00:00.000Z", sequence_no=5), SECRET, "twin")
    r1 = ingest(p, old)
    # a captured, later-numbered reading delivered after others were withheld
    held = sign(reading(timestamp="2026-11-04T10:00:10.000Z", sequence_no=50), SECRET, "twin")
    r2 = ingest(p, held)
    on = Perception([CONTRACT_VERSION], SECRET, max_age_s=30)
    r3 = ingest(on, old)
    say("P-B", "6-year-old reading and a withheld one delivered late", "EXPLOITABLE by default" if r1 == r2 == "accepted" else "not", f"default config: 2020 timestamp {r1}, withheld seq 50 {r2}; with twin.max_age_s=30: {r3}")


# ---- P-C: key confusion
def key_confusion():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ring = KeyRing({"twin": [Key("twin-ed", "EdDSA", public=priv.public_key())]})
    res = []
    for label, alg, kid in [("HS256 forged with public key as secret, alg named", "HS256", "twin-ed"), ("same, no alg, no kid", None, None), ("alg none", "none", "twin-ed")]:
        env = reading()
        mac = hmac.new(pub, json.dumps(env, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
        prov = {"signed_by": "twin", "hmac": mac, **({"alg": alg} if alg else {}), **({"kid": kid} if kid else {})}
        env["provenance"] = prov
        try:
            Perception([CONTRACT_VERSION], None, True, keyring=ring).ingest(env)
            res.append(f"{label}: accepted")
        except ContractError as e:
            res.append(f"{label}: {e.code}")
    say("P-C", "Ed25519 key attacked with HS256/none", "NOT exploitable" if all("accepted" not in r for r in res) else "EXPLOITABLE", "; ".join(res))


# ---- P-D: forged verdict accepted (Guardian link)
async def forged_verdict():
    def handler(request):
        body = json.loads(request.content)
        rd = body["reading"]
        return httpx.Response(200, json={"verdict_id": "v-forged", "reading_ref": {"reading_id": f"{rd['sensor_id']}#{rd['sequence_no']}", "sensor_id": rd["sensor_id"], "sequence_no": rd["sequence_no"]},
                                         "status": "trusted", "issued_at": "2026-11-04T10:00:00Z"})
    adapter = RestGuardianAdapter("http://guardian", httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://guardian"))
    v = await adapter.get_verdict(reading(), 1.0)
    say("P-D", "unsigned verdict from whoever answers the Guardian URL", "EXPLOITABLE (needs B2 position)" if v.status.value == "trusted" else "not", f"adapter returned status={v.status.value}, no key or signature involved")


# ---- edge PoCs
async def asgi(app, method, path, headers=None, body=b""):
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()], "client": ("1.2.3.4", 5), "server": ("brain", 80)}
    sent, status = [False], []
    async def receive():
        if sent[0]:
            return {"type": "http.disconnect"}
        sent[0] = True
        return {"type": "http.request", "body": body, "more_body": False}
    async def send(msg):
        if msg["type"] == "http.response.start":
            status.append(msg["status"])
    try:
        await asyncio.wait_for(app(scope, receive, send), 5)
    except Exception as e:  # noqa
        return f"exc:{type(e).__name__}"
    return status[0] if status else "none"


async def edge():
    from brain.api import Hub, create_app
    from brain.config import ModelsConfig, PartnersConfig, Policy
    toks = {"read": "poc-read", "admin": "poc-admin", "approve": "poc-approve", "twin": "poc-twin", "guardian": "poc-guardian"}
    envs = {"read": "BRAIN_TOKEN_READ", "admin": "BRAIN_TOKEN_ADMIN", "approve": "BRAIN_TOKEN_APPROVE", "twin": "TWIN_PUSH_TOKEN", "guardian": "GUARDIAN_PUSH_TOKEN"}
    for k, e in envs.items():
        os.environ[e] = toks[k]
    os.environ["BRAIN_TOKEN_KEY"] = "poc-token-signing-key"
    partners = PartnersConfig.model_validate({"security": {"require": "always", "rate_per_minute": 100000, "max_body_bytes": 262144}})
    hub = Hub(partners, Policy(), ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}}), mocks="inproc", log_dir=tempfile.mkdtemp())
    app = create_app(hub)
    B = lambda n: {"Authorization": f"Bearer {toks[n]}"}  # noqa

    # P-E: retraction with the Twin's token and the read token
    body = json.dumps({"reading_id": "wl-01#1", "reason": "twin says so"}).encode()
    h = {"content-type": "application/json", "content-length": str(len(body))}
    twin = await asgi(app, "POST", "/api/retractions", {**B("twin"), **h}, body)
    read = await asgi(app, "POST", "/api/retractions", {**B("read"), **h}, body)
    none = await asgi(app, "POST", "/api/retractions", h, body)
    say("P-E", "retraction by token", "EXPLOITABLE (authz)" if twin not in (401, 403) else "not", f"twin token -> {twin}; guardian token -> {await asgi(app, 'POST', '/api/retractions', {**B('guardian'), **h}, body)}; read token -> {read}; none -> {none} (404/409/503 = past the edge, the reading did not exist)")

    # P-F: route sweep without a token, every method, many path spellings
    paths = ["/api/scenarios", "/api/scenarios/", "//api/scenarios", "/API/scenarios", "/api/scenarios/t14/run", "/api/approvals", "/api/approvals/x", "/api/incidents", "/api/topology",
             "/metrics", "/events", "/api/llm", "/api/sleep", "/api/sleep/last", "/api/retractions", "/api/events", "/mcp", "/mcp/", "/docs/../api/scenarios", "/static/../api/scenarios",
             "/schemas/../api/scenarios", "/vendor/../api/scenarios", "/api/%73cenarios", "/api/scenarios%2f", "/health/../api/scenarios", "/.well-known/../api/scenarios", "/docsx", "/schemas/x"]
    leaks = []
    for p in paths:
        for m in ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
            code = await asgi(app, m, p, {"content-type": "application/json", "content-length": "2"}, b"{}")
            if code not in (401, 403, 404, 405, 422, 307, 308) and not (p in ("/schemas/x",) and code == 404):
                leaks.append(f"{m} {p} -> {code}")
    say("P-F", "unauthenticated sweep, 28 spellings x 7 methods", "NOT exploitable" if not leaks else "REVIEW", "unexpected answers: " + ("; ".join(leaks) if leaks else "none (every one 401, 403, 404, 405, 422 or a redirect)"))

    # P-G: forged JWTs
    def b64(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    claims = b64(json.dumps({"sub": "x", "scope": "admin approve push read", "aud": "city-brain", "exp": int(time.time()) + 999, "jti": "j"}).encode())
    forged = {"alg none, empty sig": f"{b64(b'{\"alg\":\"none\"}')}.{claims}.", "HS256, wrong key": f"{b64(b'{\"alg\":\"HS256\"}')}.{claims}.{b64(hmac.new(b'guess', b'x', 'sha256').digest())}",
              "static token with two dots appended": toks["read"] + ".a.b"}
    res = [f"{k}: {await asgi(app, 'GET', '/api/scenarios', {'Authorization': 'Bearer ' + v})}" for k, v in forged.items()]
    say("P-G", "forged tokens", "NOT exploitable" if all(r.endswith("401") for r in res) else "REVIEW", "; ".join(res))

    # P-H: body limit without Content-Length (chunked)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://brain") as c:
        async def gen():
            for _ in range(8):
                yield b"A" * 100_000
        r = await c.post("/api/events", content=gen(), headers={**B("twin"), "content-type": "application/json"})
        r2 = await c.post("/api/events", content=b"A" * 800_000, headers={**B("twin"), "content-type": "application/json"})
    say("P-H", "800 KB body with no Content-Length (limit is 256 KiB)", "limit bypassed" if r.status_code != 413 else "NOT bypassed", f"chunked -> {r.status_code}; with length -> {r2.status_code}")

    # P-I: push token spoofing / namespace
    ev = lambda t, s: json.dumps({"specversion": "1.0", "id": "e1", "type": t, "source": s, "data": {}}).encode()  # noqa
    cases = {"twin->guardian.x": ("twin", "guardian.x", "guardian"), "twin->brain.x": ("twin", "brain.x", "twin"), "twin->twin.x with source guardian": ("twin", "twin.x", "guardian"), "read->twin.x": ("read", "twin.x", "twin")}
    res = []
    for k, (tok, t, s) in cases.items():
        b = ev(t, s)
        res.append(f"{k}: {await asgi(app, 'POST', '/api/events', {**B(tok), 'content-type': 'application/json', 'content-length': str(len(b))}, b)}")
    say("P-I", "timeline push spoofing", "see detail", "; ".join(res))

    # P-J: cookie auth: forged cookie, CSRF shape
    ck = await asgi(app, "GET", "/api/scenarios", {"cookie": "brain_session=made-up"})
    say("P-J", "made-up session cookie", "NOT exploitable" if ck == 401 else "REVIEW", f"-> {ck}")

    # P-K: schema route traversal
    res = [f"{p}: {await asgi(app, 'GET', p)}" for p in ["/schemas/..", "/schemas/..%2f..%2fpyproject", "/schemas/%2e%2e", "/schemas/reading.water_level%00"]]
    say("P-K", "schema file route traversal", "NOT exploitable" if all(r.endswith(("404", "401", "403")) for r in res) else "REVIEW", "; ".join(res))

    # P-L: scenario id traversal (admin token)
    res = [f"{p}: {await asgi(app, 'POST', p, B('admin'))}" for p in ["/api/scenarios/..%2f..%2fpyproject/run", "/api/scenarios/../x/run", "/api/scenarios/%2e%2e/run"]]
    say("P-L", "scenario id traversal with admin token", "see detail", "; ".join(res))

    # P-M: MCP DNS rebinding
    res = [f"Host {h}: {await asgi(app, 'POST', '/mcp', {**B('read'), 'host': h, 'content-type': 'application/json', 'accept': 'application/json, text/event-stream', 'content-length': '2'}, b'{}')}" for h in ("evil.example", "127.0.0.1:8080")]
    say("P-M", "MCP with a hostile Host header", "see detail", "; ".join(res))


async def main():
    sig_coverage(); stale(); key_confusion(); await forged_verdict(); await edge()
    if out := os.environ.get("POC_OUT"):
        json.dump(OUT, open(out, "w"), indent=1)

asyncio.run(main())
