"""Signing with key ids, algorithms and rotation: an old key works inside its overlap and not after, nothing unlisted is accepted, old signatures still verify."""

from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from brain.config import KeyConfig, ModelsConfig, PartnersConfig, Policy
from brain.contracts import CONTRACT_VERSION
from brain.contracts.keyring import KeyRing
from brain.contracts.signing import sign
from brain.perception import ContractError, Perception

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)
READING = {"contract_version": CONTRACT_VERSION, "sensor_id": "wl-01", "type": "water_level", "zone_id": "zone-01",
           "timestamp": "2026-11-20T11:59:00.000Z", "sequence_no": 1, "value": {"level_m": 0.4, "flow_rate_m3s": 1.0}}


def ring(env, *keys):
    return KeyRing.from_config({"twin": list(keys)}, env)


def test_a_reading_with_no_kid_verifies_against_the_current_key_as_today():
    keys = ring({"NEW": "new-secret", "OLD": "old-secret"}, KeyConfig(kid="2026-11", secret_env="NEW"), KeyConfig(kid="2026-10", secret_env="OLD"))

    assert keys.verify("twin", sign(READING, "new-secret", "twin"), NOW) is None
    assert keys.verify("twin", sign(READING, "old-secret", "twin"), NOW) == "signature_invalid"  # no kid: only the current key is tried


def test_a_reading_signed_with_the_previous_key_is_accepted_inside_the_overlap_and_refused_after():
    keys = ring({"NEW": "new-secret", "OLD": "old-secret"}, KeyConfig(kid="2026-11", secret_env="NEW"),
                KeyConfig(kid="2026-10", secret_env="OLD", not_after=date(2026, 11, 20)))
    old = keys.keys["twin"][1]
    old_signed = KeyRing({"twin": [old]}).sign("twin", READING, "twin")

    assert keys.verify("twin", old_signed, NOW) is None
    assert keys.verify("twin", old_signed, NOW + timedelta(days=1)) == "signature_key_expired"


def test_an_unknown_kid_is_refused_with_signature_unknown_key():
    keys = ring({"NEW": "s"}, KeyConfig(kid="2026-11", secret_env="NEW"))
    signed = sign(READING, "s", "twin")
    signed["provenance"]["kid"] = "attacker"

    assert keys.verify("twin", signed, NOW) == "signature_unknown_key"


def test_alg_none_and_an_unlisted_alg_are_refused():
    keys = ring({"NEW": "s"}, KeyConfig(kid="k", secret_env="NEW"))
    for alg in ("none", "HS512", "RS256"):
        signed = sign(READING, "s", "twin")
        signed["provenance"]["alg"] = alg
        assert keys.verify("twin", signed, NOW) == "signature_alg_not_allowed"
    downgraded = KeyRing.from_config({"twin": [KeyConfig(kid="ed", alg="EdDSA", public_key=_keypair()[1])]})
    hs = sign(READING, "s", "twin")
    hs["provenance"].update(kid="ed", alg="HS256")
    assert downgraded.verify("twin", hs, NOW) == "signature_alg_not_allowed"  # an EdDSA key cannot be checked as an HMAC


def _keypair():
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
    key = Ed25519PrivateKey.generate()
    return (b64(key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())),
            b64(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)))


def test_an_ed25519_signature_verifies_with_the_public_key_and_not_with_another():
    seed, public = _keypair()
    _, other = _keypair()
    signer = KeyRing.from_config({"twin": [KeyConfig(kid="ed1", alg="EdDSA", private_key_env="SEED")]}, {"SEED": seed})
    signed = signer.sign("twin", READING, "twin")

    assert signed["provenance"]["kid"] == "ed1" and signed["provenance"]["alg"] == "EdDSA"
    assert KeyRing.from_config({"twin": [KeyConfig(kid="ed1", alg="EdDSA", public_key=public)]}).verify("twin", signed, NOW) is None
    assert KeyRing.from_config({"twin": [KeyConfig(kid="ed1", alg="EdDSA", public_key=other)]}).verify("twin", signed, NOW) == "signature_invalid"
    tampered = {**signed, "value": {"level_m": 9.9, "flow_rate_m3s": 1.0}}
    assert KeyRing.from_config({"twin": [KeyConfig(kid="ed1", alg="EdDSA", public_key=public)]}).verify("twin", tampered, NOW) == "signature_invalid"


def test_the_canonical_form_is_unchanged_so_old_signatures_still_verify():
    legacy = sign(READING, "twin-secret", "twin")  # as signed before key ids existed

    assert legacy["provenance"] == {"signed_by": "twin", "hmac": legacy["provenance"]["hmac"]}
    assert KeyRing.from_secret("twin", "twin-secret").verify("twin", legacy, NOW) is None


def test_perception_gives_the_ring_s_reason_as_the_rejection_code():
    perception = Perception([CONTRACT_VERSION], None, True, keyring=ring({"NEW": "s"}, KeyConfig(kid="k", secret_env="NEW")))
    bad = sign(READING, "s", "twin")
    bad["provenance"]["kid"] = "nobody"

    with pytest.raises(ContractError) as error:
        perception.ingest(bad)
    assert error.value.code == "signature_unknown_key"


def test_the_brain_publishes_its_public_key_at_jwks_and_never_the_private_one():
    from brain.api import Hub, create_app

    seed, public = _keypair()
    partners = PartnersConfig.model_validate({"security": {"keys": {"brain": [{"kid": "d1", "alg": "EdDSA", "public_key": public}]}}})
    hub = Hub(partners, Policy(), ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}}), mocks="inproc")

    async def get():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
            return await client.get("/.well-known/jwks.json")

    import asyncio

    body = asyncio.run(get()).json()
    assert body["keys"][0]["kid"] == "d1" and body["keys"][0]["x"] == public and "d" not in body["keys"][0] and seed not in str(body)


# ---- signed actuator calls: time and a one-time number

def test_an_actuator_call_outside_the_skew_is_refused_and_a_repeated_nonce_is_refused():
    from brain.contracts import ActuatorCall
    from brain.contracts.signing import sign as sign_call
    from mocks.twin.engine import MockTwin

    twin = MockTwin(None, "brain-secret", skew_s=30)
    now = datetime.now(UTC)

    def call(issued_at, nonce):
        body = ActuatorCall(actuator_id="x", action="broadcast_alert", params={"message": "m", "channel": "app", "zone_id": "zone-01"}, justification="j",
                            trust_ref="v1", issued_at=issued_at, nonce=nonce).model_dump(mode="json", exclude={"provenance"})
        return sign_call(body, "brain-secret", "city_brain")

    assert twin._accept(call(now, "n1"), "broadcast_alert")[1] == ""
    assert "call_expired" in twin._accept(call(now - timedelta(minutes=5), "n2"), "broadcast_alert")[1]
    assert "nonce_reused" in twin._accept(call(now, "n1"), "broadcast_alert")[1]
