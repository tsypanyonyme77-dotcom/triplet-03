"""Who may call the API: scoped tokens off loopback, size and rate limits, and a push boundary that nobody can speak as the Brain through."""

import json

import httpx

from brain.api import Hub, create_app
from brain.config import ModelsConfig, PartnersConfig, Policy

MODELS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})
TOKENS = {"BRAIN_TOKEN_READ": "read-secret-1", "BRAIN_TOKEN_ADMIN": "admin-secret-1", "BRAIN_TOKEN_APPROVE": "approve-secret-1",
          "TWIN_PUSH_TOKEN": "twin-push-secret-1", "GUARDIAN_PUSH_TOKEN": "guardian-push-secret-1"}


def make(tmp_path, monkeypatch, require="always", **security):
    for name, value in TOKENS.items():
        monkeypatch.setenv(name, value)
    partners = PartnersConfig.model_validate({"security": {"require": require, **security}})
    hub = Hub(partners, Policy(), MODELS, mocks="inproc", log_dir=tmp_path)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain")


def bearer(name):
    return {"Authorization": f"Bearer {TOKENS[name]}"}


def event(type, source="twin", **extra):
    return {"specversion": "1.0", "type": type, "source": source, "data": {}, **extra}


async def test_on_loopback_with_auto_nothing_changes(tmp_path, monkeypatch):
    async with make(tmp_path, monkeypatch, require="auto") as client:
        assert (await client.get("/api/scenarios")).status_code == 200
        assert (await client.post("/api/events", json=event("twin.reading.sent"))).status_code == 202


async def test_off_loopback_a_read_without_a_token_is_401_and_health_stays_open(tmp_path, monkeypatch):
    async with make(tmp_path, monkeypatch) as client:
        assert (await client.get("/api/scenarios")).status_code == 401
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/schemas")).status_code == 200


async def test_a_read_token_cannot_push_run_or_approve(tmp_path, monkeypatch):
    async with make(tmp_path, monkeypatch) as client:
        assert (await client.get("/api/scenarios", headers=bearer("BRAIN_TOKEN_READ"))).status_code == 200
        assert (await client.post("/api/events", json=event("twin.x"), headers=bearer("BRAIN_TOKEN_READ"))).status_code == 403
        assert (await client.post("/api/scenarios/t14/run", headers=bearer("BRAIN_TOKEN_READ"))).status_code == 403
        assert (await client.post("/api/sleep", headers=bearer("BRAIN_TOKEN_READ"))).status_code == 403


async def test_a_wrong_token_is_401_and_the_body_never_contains_it(tmp_path, monkeypatch):
    async with make(tmp_path, monkeypatch) as client:
        response = await client.get("/api/scenarios", headers={"Authorization": "Bearer not-a-real-token-xyz"})

    assert response.status_code == 401
    assert "not-a-real-token-xyz" not in response.text and TOKENS["BRAIN_TOKEN_READ"] not in response.text


async def test_a_login_cookie_works_like_a_header(tmp_path, monkeypatch):
    async with make(tmp_path, monkeypatch) as client:
        assert (await client.post("/api/login", json={"token": "nope"})).status_code == 401
        login = await client.post("/api/login", json={"token": TOKENS["BRAIN_TOKEN_READ"]})
        assert login.status_code == 200 and "httponly" in login.headers["set-cookie"].lower()
        assert (await client.get("/api/scenarios")).status_code == 200  # the client keeps the cookie


async def test_an_oversize_body_is_413(tmp_path, monkeypatch):
    async with make(tmp_path, monkeypatch, max_body_bytes=2000) as client:
        big = event("twin.big", data={"pad": "A" * 5000})
        assert (await client.post("/api/events", json=big, headers=bearer("TWIN_PUSH_TOKEN"))).status_code == 413


async def test_the_rate_limit_answers_429_with_retry_after(tmp_path, monkeypatch):
    async with make(tmp_path, monkeypatch, rate_per_minute=3) as client:
        codes = [(await client.get("/api/scenarios", headers=bearer("BRAIN_TOKEN_READ"))).status_code for _ in range(5)]
        limited = await client.get("/api/scenarios", headers=bearer("BRAIN_TOKEN_READ"))

    assert codes[:3] == [200, 200, 200] and 429 in codes
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) >= 1


async def test_security_headers_are_on_every_response(tmp_path, monkeypatch):
    async with make(tmp_path, monkeypatch, require="auto") as client:
        headers = (await client.get("/health")).headers

    assert headers["x-content-type-options"] == "nosniff" and "default-src 'self'" in headers["content-security-policy"]
    assert "access-control-allow-origin" not in headers


# ---- the push boundary (audit finding F1)


async def test_a_pushed_event_in_the_brain_namespace_is_refused(tmp_path, monkeypatch):
    async with make(tmp_path, monkeypatch, require="auto") as client:
        for source in ("twin", "city-brain", "guardian"):
            response = await client.post("/api/events", json=event("brain.action.result", source=source))
            assert response.status_code in (403, 422), source
        assert (await client.post("/api/events", json=event("brain.session.reset"))).status_code == 403


async def test_a_partner_may_push_only_inside_its_own_namespace(tmp_path, monkeypatch):
    async with make(tmp_path, monkeypatch, require="auto") as client:
        assert (await client.post("/api/events", json=event("twin.sensor.stuck", source="twin"))).status_code == 202
        assert (await client.post("/api/events", json=event("guardian.verdict.issued", source="twin"))).status_code == 403


async def test_a_pushed_event_takes_its_source_from_the_token_not_the_body(tmp_path, monkeypatch):
    async with make(tmp_path, monkeypatch) as client:
        # the body says guardian, the token is the Twin's: the Twin may not speak as the Guardian
        lie = await client.post("/api/events", json=event("guardian.verdict.issued", source="guardian"), headers=bearer("TWIN_PUSH_TOKEN"))
        ok = await client.post("/api/events", json=event("twin.reading.stuck", source="guardian"), headers=bearer("TWIN_PUSH_TOKEN"))
        stream = await client.get("/events", params={"once": True}, headers=bearer("BRAIN_TOKEN_READ"))

    assert lie.status_code == 403 and ok.status_code == 202
    pushed = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
    row = next(e for e in pushed if e["type"] == "twin.reading.stuck")
    assert row["source"] == "twin" and row["pushed"] is True


async def test_a_pushed_event_is_marked_pushed_in_the_stream(tmp_path, monkeypatch):
    async with make(tmp_path, monkeypatch, require="auto") as client:
        await client.post("/api/events", json=event("twin.sensor.stuck"))
        stream = await client.get("/events", params={"once": True})

    rows = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
    assert next(e for e in rows if e["type"] == "twin.sensor.stuck")["pushed"] is True


def test_the_screen_ignores_a_brain_event_that_was_pushed_or_has_another_source():
    from pathlib import Path

    html = (Path(__file__).parents[1] / "src/brain/api/static/index.html").read_text()

    assert 'type.startsWith("brain.") && (e.source !== "city-brain" || e.pushed)' in html
    assert 'e.type === "brain.session.reset" && e.source === "city-brain" && !e.pushed' in html


def test_every_route_has_a_scope_or_is_on_the_public_list():
    from brain.security import scope_for

    hub = Hub(PartnersConfig(), Policy(), MODELS, mocks="inproc")
    for route in create_app(hub).routes:
        for method in getattr(route, "methods", None) or []:
            if method in ("HEAD", "OPTIONS"):
                continue
            assert scope_for(method, route.path) != "UNCLASSIFIED", f"{method} {route.path}"


def test_serve_refuses_to_start_off_loopback_without_tokens(monkeypatch):
    from brain.cli import build_parser, cmd_serve

    for name in ("BRAIN_TOKEN_READ", "BRAIN_TOKEN_ADMIN", "BRAIN_TOKEN_APPROVE", "TWIN_PUSH_TOKEN", "GUARDIAN_PUSH_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    assert cmd_serve(build_parser().parse_args(["serve", "--host", "0.0.0.0"])) == 2


async def test_approvals_are_listed_and_answered_over_the_api_with_the_approve_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_APPROVAL_SECRET", "api-approval-secret")
    for name, value in TOKENS.items():
        monkeypatch.setenv(name, value)
    partners = PartnersConfig.model_validate({"security": {"require": "always"}, "approval": {"mode": "human", "path": ":memory:"}})
    hub = Hub(partners, Policy(), MODELS, mocks="inproc", log_dir=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        listing = await client.get("/api/approvals", headers=bearer("BRAIN_TOKEN_READ"))
        assert listing.status_code == 404  # no run yet
        denied = await client.post("/api/approvals/pending-000001", json={"decision": "grant"}, headers=bearer("BRAIN_TOKEN_READ"))
        assert denied.status_code == 403


async def test_answering_an_unknown_approval_is_404_and_a_bad_decision_is_422(tmp_path, monkeypatch):
    from brain.approval import ApprovalStore

    monkeypatch.setenv("BRAIN_APPROVAL_SECRET", "api-approval-secret")
    partners = PartnersConfig.model_validate({"approval": {"mode": "human", "path": ":memory:"}})
    hub = Hub(partners, Policy(), MODELS, mocks="inproc", log_dir=tmp_path)

    class Service:
        approvals = ApprovalStore(":memory:", "api-approval-secret")

        async def reoffer(self, pending_id):
            return []

    hub.service = Service()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        assert (await client.get("/api/approvals")).json() == {"mode": "human", "pending": []}
        assert (await client.post("/api/approvals/nope", json={"decision": "grant"})).status_code == 404
        assert (await client.post("/api/approvals/nope", json={"decision": "maybe"})).status_code == 422


def test_the_screen_lets_only_the_brains_own_events_raise_a_bar_or_a_button():
    from pathlib import Path

    html = (Path(__file__).parents[1] / "src/brain/api/static/index.html").read_text()

    for kind in ("brain.llm.status", "brain.human.needed", "brain.approval.requested"):
        assert f'own && e.type === "{kind}"' in html, kind


async def test_only_the_guardians_push_token_may_retract_a_verdict(tmp_path, monkeypatch):
    body = {"reading_id": "wl-01#1", "reason": "faulty"}
    async with make(tmp_path, monkeypatch) as client:
        codes = {who: (await client.post("/api/retractions", json=body, headers=bearer(who))).status_code
                 for who in ("TWIN_PUSH_TOKEN", "BRAIN_TOKEN_READ", "BRAIN_TOKEN_APPROVE", "GUARDIAN_PUSH_TOKEN", "BRAIN_TOKEN_ADMIN")}
        none = (await client.post("/api/retractions", json=body)).status_code

    assert codes["TWIN_PUSH_TOKEN"] == 403 and codes["BRAIN_TOKEN_READ"] == 403 and codes["BRAIN_TOKEN_APPROVE"] == 403 and none == 401
    assert codes["BRAIN_TOKEN_ADMIN"] == 403  # admin is not a push scope: the edge refuses it
    assert codes["GUARDIAN_PUSH_TOKEN"] == 404  # past the edge and the check: the Brain has no such reading
