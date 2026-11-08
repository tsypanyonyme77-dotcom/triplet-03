"""`brain env`: what a run depends on, in one place, so two runs can be compared and a replay can warn about a difference.

It names the code (version, commit and whether the tree is dirty), the locked dependencies (a hash of `uv.lock` and the versions
of the packages that decide behaviour), the machine (Python, platform, hash seed), the embedding model (its name and a hash of its
weights file), the language models the team would use, the tuned overlay, and whether the clock is real. It never holds a secret:
only names and hashes.
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from brain import clock, config

PACKAGES = ("langgraph", "langchain", "langchain-core", "mcp", "numpy", "neo4j", "networkx", "pydantic", "fastapi", "fastembed", "httpx")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "none"


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=config.home(), capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _commit() -> str:
    head = _git("rev-parse", "--short", "HEAD")
    if head is None:
        return "no git"
    dirty = _git("status", "--porcelain", "--", ".")
    return f"{head}+dirty:{hashlib.sha256((dirty or '').encode()).hexdigest()[:8]}" if dirty else head


def _version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not installed"


def _embedder_weights() -> str:
    """A hash of the cached embedding model's weights file, or `none` when it is not cached (the hashing embedder runs then)."""
    from brain.knowledge.embedding import model_cache_dir

    files = sorted(Path(model_cache_dir()).rglob("*.onnx")) if Path(model_cache_dir()).exists() else []
    return _sha256(files[0]) if files else "none"


def fingerprint_env(lock: Path | None = None) -> dict[str, Any]:
    models = config.load(config.ModelsConfig, "models")
    partners = config.load(config.PartnersConfig, "partners")
    return {
        "brain": _version("brain"),
        "commit": _commit(),
        "lock_sha256": _sha256(lock or config.home() / "uv.lock"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": {name: _version(name) for name in PACKAGES},
        "embedder": {"provider": models.embeddings.provider, "weights_sha256": _embedder_weights()},
        "models": {"roles": models.roles, "llm": models.team.llm, "cassette": models.team.cassette, "relative_times": models.team.relative_times},
        "overlay": {"tuned_dir": partners.brain.tuned_dir, "sha256": _sha256(Path(partners.brain.tuned_dir) / "overlay.yaml") if partners.brain.tuned_dir else "none"},
        "clock": "deterministic" if clock.current().deterministic else "system",
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "image_digest": os.environ.get("BRAIN_IMAGE_DIGEST"),
    }
