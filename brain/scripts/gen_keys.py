"""Make an Ed25519 key pair for signing: prints the private seed (keep it secret, put it in an environment variable) and the public key (share it).

    uv run python scripts/gen_keys.py [kid]
"""

import base64
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
key = Ed25519PrivateKey.generate()
seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
kid = sys.argv[1] if len(sys.argv) > 1 else "brain-key-1"
print(f"kid:         {kid}\nprivate key: {b64(seed)}   <- BRAIN_SIGNING_KEY=..., never commit\npublic key:  {b64(public)}   <- share with the partner")
