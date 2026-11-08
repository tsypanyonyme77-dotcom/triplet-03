# Signing keys: how to rotate them

Every reading and every actuator call is signed. Each peer (`twin`, `guardian`, `brain`) has a list of keys in `config/partners.yaml` under `security.keys`; **the first key is the current one**. A signed envelope may name the key it used (`provenance.kid`, `provenance.alg`); without them the current key is tried, which is how everything was checked before key ids existed. The signed bytes are unchanged, so old signatures still verify.

Two algorithms: `HS256` (a shared secret, as today) and `EdDSA` (Ed25519: the checker holds only a public key). Anything else, including `none`, is refused.

## Rotate a shared secret in four commands

```bash
openssl rand -hex 32                                # 1. a new secret; give it to the partner over a channel you trust
export TWIN_HMAC_SECRET_2026_12=<the new secret>    # 2. next to the old one, which stays in TWIN_HMAC_SECRET
$EDITOR config/partners.yaml                        # 3. put the new key first, give the old one an end date (below)
uv run brain scenario t14 --inproc --speed 0         # 4. check nothing broke; restart the Brain
```

```yaml
security:
  keys:
    twin:
      - {kid: twin-2026-12, alg: HS256, secret_env: TWIN_HMAC_SECRET_2026_12}
      - {kid: twin-2026-11, alg: HS256, secret_env: TWIN_HMAC_SECRET, not_after: 2026-12-05}   # accepted until the end of this day
```

Readings that name `twin-2026-11` are accepted until the end of 5 Dec and then refused with `signature_key_expired`; a `kid` nobody has is refused with `signature_unknown_key`. Once the partner signs with the new key, remove the old entry.

## Use Ed25519 (no shared secret)

```bash
uv run python scripts/gen_keys.py brain-2026-12     # prints a private seed and a public key
export BRAIN_SIGNING_KEY=<the private seed>         # stays on this machine
```

```yaml
security:
  keys:
    brain:
      - {kid: brain-2026-12, alg: EdDSA, private_key_env: BRAIN_SIGNING_KEY}
```

The Brain then signs its actuator calls with that key and publishes the public half at `GET /.well-known/jwks.json`, so the Twin can verify them with no secret to guard. To check a partner that signs with Ed25519, list its public key: `{kid: twin-1, alg: EdDSA, public_key: <base64url, or the path of a file holding it>}`.

## Time and a one-time number

Every actuator call carries `issued_at` and a `nonce` inside the signed bytes. A receiver may refuse a call more than `security.clock_skew_s` (30 s) from its own clock and a nonce it has seen before; the shipped mock Twin does both. This is what stops a captured call being sent again.

## What is not done

The Twin and Guardian mocks sign with a shared secret only (they do not yet use key ids); the mock Twin can sign each reading with a named key (`sign_with` and `signing_keys` in a scenario file; no demo scenario uses it now). Rotation is covered by `tests/test_signing_keys.py` and `brain redteam` attack A21: the new key and a previous key inside its overlap are accepted, a key retired yesterday is refused with `signature_key_expired`, an unknown key with `signature_unknown_key`. A real Twin team has to adopt `kid` before rotation protects anything on its side: until then the field is a proposal (see `INTERFACE.md`).
