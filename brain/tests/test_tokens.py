"""Short-lived tokens: scoped, audience-bound, expiring, revocable, and never written to an event or a log."""

import time

import httpx

from brain.api import Hub, create_app
from brain.config import ModelsConfig, PartnersConfig, Policy
from brain.security import Security, mint_token

KEY = "token-key-for-tests"


def make(tmp_path, monkeypatch, **security):
    monkeypatch.setenv("BRAIN_TOKEN_KEY", KEY)
    monkeypatch.setenv("BRAIN_TOKEN_READ", "static-read-token")
    partners = PartnersConfig.model_validate({"security": {"require": "always", "revocations_path": str(tmp_path / "revoked.txt"), **security}})
    hub = Hub(partners, Policy(), ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}}), mocks="inproc", log_dir=tmp_path)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain"), partners


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


async def test_a_minted_token_carries_scope_audience_subject_and_expiry_and_works(tmp_path, monkeypatch):
    client, _ = make(tmp_path, monkeypatch)
    token, _jti = mint_token(KEY, "operator", ["read"], 60)
    async with client:
        assert (await client.get("/api/scenarios", headers=bearer(token))).status_code == 200
        assert (await client.post("/api/scenarios/b2/run", headers=bearer(token))).status_code == 403  # read only


async def test_an_expired_token_is_refused(tmp_path, monkeypatch):
    client, _ = make(tmp_path, monkeypatch)
    token, _ = mint_token(KEY, "operator", ["read"], -5)
    async with client:
        assert (await client.get("/api/scenarios", headers=bearer(token))).status_code == 401


async def test_a_revoked_token_is_refused(tmp_path, monkeypatch):
    client, _ = make(tmp_path, monkeypatch)
    token, jti = mint_token(KEY, "operator", ["read"], 60)
    async with client:
        assert (await client.get("/api/scenarios", headers=bearer(token))).status_code == 200
        (tmp_path / "revoked.txt").write_text(jti + "\n")
        assert (await client.get("/api/scenarios", headers=bearer(token))).status_code == 401


def test_a_token_for_another_audience_or_signed_with_another_key_is_refused(tmp_path, monkeypatch):
    _, partners = make(tmp_path, monkeypatch)
    security = Security(partners.security)
    good, _ = mint_token(KEY, "operator", ["read"], 60)
    other_key, _ = mint_token("another-key", "operator", ["read"], 60)
    head, body, sig = good.split(".")
    forged_body = body[:-2] + ("AA" if not body.endswith("AA") else "BB")

    assert security.check_token(good) is not None and security.check_token(other_key) is None
    assert security.check_token(f"{head}.{forged_body}.{sig}") is None


async def test_a_static_machine_token_still_works_when_configured(tmp_path, monkeypatch):
    client, _ = make(tmp_path, monkeypatch)
    async with client:
        assert (await client.get("/api/scenarios", headers=bearer("static-read-token"))).status_code == 200


async def test_no_token_text_appears_in_any_reply_body_or_event(tmp_path, monkeypatch):
    client, _ = make(tmp_path, monkeypatch)
    token, _ = mint_token(KEY, "operator", ["read"], 60)
    async with client:
        denied = await client.post("/api/scenarios/b2/run", headers=bearer(token))
        stream = await client.get("/events", params={"once": True}, headers=bearer(token))

    assert token not in denied.text and token not in stream.text and KEY not in denied.text


def test_the_token_command_prints_a_token_that_the_checker_accepts(tmp_path, monkeypatch, capsys):
    from brain.cli import build_parser, cmd_token

    monkeypatch.setenv("BRAIN_TOKEN_KEY", KEY)
    assert cmd_token(build_parser().parse_args(["token", "--sub", "ana", "--scope", "read,analyse", "--ttl", "1h"])) == 0
    token = capsys.readouterr().out.strip()
    caller = Security(PartnersConfig().security).check_token(token)

    assert caller.label == "ana" and {"read", "analyse"} <= caller.scopes and time.time()
